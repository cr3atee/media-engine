from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.domain.identity import normalize_utc
from app.domain.lifecycle import (
    EventDisposition,
    InvalidLifecycleTransition,
    ScoringStatus,
    validate_event_disposition_transition,
    validate_scoring_status_transition,
)
from app.domain.market_events import (
    ClaimedMarketEvent,
    EventAddResult,
    MarketEventCandidate,
    PriceDropMarketEvent,
    SnapshotIdentity,
)
from app.domain.processing import (
    IdempotentCreateStatus,
    ProcessingError,
    StateTransitionOutcome,
    StateTransitionResult,
    WorkClaim,
)
from app.models.market_event_record import MarketEventRecord
from app.models.price_snapshot_record import PriceSnapshotRecord
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.events import MarketEventRepository, event_immutable_signature
from app.repositories.postgres.market_event_mapping import (
    market_event_to_domain,
    market_event_values,
)

type ClaimTokenFactory = Callable[[], UUID]
type EventRow = tuple[
    MarketEventRecord,
    PriceSnapshotRecord,
    PriceSnapshotRecord,
]
type EventDatabaseRow = Row[EventRow]

_ELIGIBLE_DISPOSITIONS = (
    EventDisposition.ACTIVE.value,
    EventDisposition.APPROVED.value,
)
_PreviousSnapshot = aliased(PriceSnapshotRecord, name="previous_snapshot")
_CurrentSnapshot = aliased(PriceSnapshotRecord, name="current_snapshot")


class PostgresMarketEventRepository(MarketEventRepository):
    """PostgreSQL persistence for durable market-event lifecycles."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        claim_token_factory: ClaimTokenFactory = uuid4,
    ) -> None:
        """Bind the repository to a caller-owned session and transaction."""
        self._session = session
        self._claim_token_factory = claim_token_factory

    async def add_idempotently(
        self,
        candidate: MarketEventCandidate,
    ) -> EventAddResult:
        """Race-safely insert one event after resolving exact snapshots."""
        event = candidate.event
        previous_id = await self._resolve_snapshot_id(event.previous_snapshot)
        current_id = await self._resolve_snapshot_id(event.current_snapshot)
        statement = (
            insert(MarketEventRecord)
            .values(
                market_event_values(
                    event,
                    previous_snapshot_id=previous_id,
                    current_snapshot_id=current_id,
                )
            )
            .on_conflict_do_nothing()
            .returning(MarketEventRecord.id)
        )
        result = await self._session.execute(statement)
        inserted_id = result.scalar_one_or_none()
        if inserted_id is not None:
            stored = await self.get_by_id(inserted_id)
            assert stored is not None
            return EventAddResult(
                event=stored,
                status=IdempotentCreateStatus.CREATED,
            )

        existing = await self._find_conflicting_event(
            event,
            previous_snapshot_id=previous_id,
            current_snapshot_id=current_id,
        )
        if existing is None or event_immutable_signature(
            existing,
        ) != event_immutable_signature(event):
            msg = (
                "Market event identity conflicts with immutable event data: "
                f"{event.identity_key}."
            )
            raise RepositoryIdentityConflictError(msg)
        return EventAddResult(
            event=existing,
            status=IdempotentCreateStatus.EXISTING,
        )

    async def get_by_id(self, event_id: UUID) -> PriceDropMarketEvent | None:
        """Return one immutable event snapshot by technical identifier."""
        row = await self._get_event_row(
            self._event_query().where(MarketEventRecord.id == event_id),
        )
        return self._map_row(row) if row is not None else None

    async def get_by_identity(
        self,
        identity_key: str,
    ) -> PriceDropMarketEvent | None:
        """Return one immutable event snapshot by deterministic identity."""
        row = await self._get_event_row(
            self._event_query().where(
                MarketEventRecord.identity_key == identity_key,
            ),
        )
        return self._map_row(row) if row is not None else None

    async def list_pending(
        self,
        now: datetime,
        limit: int,
    ) -> Sequence[PriceDropMarketEvent]:
        """List eligible scoring work in deterministic readiness order."""
        now = normalize_utc(now, field_name="now")
        _validate_limit(limit)
        if limit == 0:
            return ()
        result = await self._session.execute(
            self._event_query()
            .where(_claimable_at(now))
            .order_by(*_claim_order())
            .limit(limit)
        )
        return tuple(self._map_row(row) for row in result.all())

    async def claim_pending(
        self,
        now: datetime,
        worker_id: str,
        lease_until: datetime,
        limit: int,
    ) -> Sequence[ClaimedMarketEvent]:
        """Claim eligible rows using ``FOR UPDATE SKIP LOCKED``."""
        now, lease_until, worker_id = _validate_claim_request(
            now,
            lease_until,
            worker_id,
        )
        _validate_limit(limit)
        if limit == 0:
            return ()
        result = await self._session.execute(
            self._event_query()
            .where(_claimable_at(now))
            .order_by(*_claim_order())
            .limit(limit)
            .with_for_update(of=MarketEventRecord, skip_locked=True)
        )
        rows = result.all()
        claimed: list[ClaimedMarketEvent] = []
        for row in rows:
            record = row[0]
            next_version = record.version + 1
            token = self._claim_token_factory()
            record.scoring_status = ScoringStatus.IN_PROGRESS.value
            record.scoring_attempt_count += 1
            record.next_retry_at = None
            record.claim_token = token
            record.worker_id = worker_id
            record.claimed_at = now
            record.lease_expires_at = lease_until
            record.last_error_code = None
            record.last_error_summary = None
            record.updated_at = max(record.updated_at, now)
            record.version = next_version
            claim = WorkClaim(
                token=token,
                worker_id=worker_id,
                claimed_at=now,
                lease_expires_at=lease_until,
                version=next_version,
            )
            event = self._map_row(row)
            claimed.append(ClaimedMarketEvent(event=event, claim=claim))
        await self._session.flush()
        return tuple(claimed)

    async def mark_scored(
        self,
        event_id: UUID,
        claim_token: UUID,
        expected_version: int,
        score: int,
        completed_at: datetime,
    ) -> StateTransitionResult:
        """Complete scoring under claim-token and optimistic-version guards."""
        completed_at = normalize_utc(completed_at, field_name="completed_at")
        if not 0 <= score <= 100:
            msg = "Event score must be between 0 and 100."
            raise ValueError(msg)
        record = await self._get_record_for_update(event_id)
        guarded = _guard_claim(record, event_id, claim_token, expected_version)
        if guarded is not None:
            return guarded
        assert record is not None
        validate_scoring_status_transition(
            ScoringStatus(record.scoring_status),
            ScoringStatus.SUCCEEDED,
        )
        record.scoring_status = ScoringStatus.SUCCEEDED.value
        record.score = score
        record.next_retry_at = None
        _clear_claim(record)
        _clear_error(record)
        return await self._finish_update(record, completed_at)

    async def list_expired_scoring_claims(
        self,
        now: datetime,
        limit: int,
    ) -> Sequence[ClaimedMarketEvent]:
        """Lock expired scoring claims for bounded recovery with SKIP LOCKED."""
        now = normalize_utc(now, field_name="now")
        _validate_limit(limit)
        if limit == 0:
            return ()
        result = await self._session.execute(
            self._event_query()
            .where(
                MarketEventRecord.scoring_status == ScoringStatus.IN_PROGRESS.value,
                MarketEventRecord.lease_expires_at <= now,
            )
            .order_by(
                MarketEventRecord.lease_expires_at,
                MarketEventRecord.created_at,
                MarketEventRecord.id,
            )
            .limit(limit)
            .with_for_update(of=MarketEventRecord, skip_locked=True)
        )
        claimed: list[ClaimedMarketEvent] = []
        for row in result.all():
            event = self._map_row(row)
            assert event.claim is not None
            claimed.append(ClaimedMarketEvent(event=event, claim=event.claim))
        return tuple(claimed)

    async def mark_scoring_failed(
        self,
        event_id: UUID,
        claim_token: UUID,
        expected_version: int,
        error: ProcessingError,
        failed_at: datetime,
        next_retry_at: datetime | None,
    ) -> StateTransitionResult:
        """Record a known scoring failure and optional retry eligibility."""
        failed_at = normalize_utc(failed_at, field_name="failed_at")
        next_retry_at = _normalize_optional_utc(
            next_retry_at,
            field_name="next_retry_at",
        )
        record = await self._get_record_for_update(event_id)
        guarded = _guard_claim(record, event_id, claim_token, expected_version)
        if guarded is not None:
            return guarded
        assert record is not None
        validate_scoring_status_transition(
            ScoringStatus(record.scoring_status),
            ScoringStatus.FAILED,
        )
        record.scoring_status = ScoringStatus.FAILED.value
        record.score = None
        record.next_retry_at = next_retry_at
        _clear_claim(record)
        record.last_error_code = error.code
        record.last_error_summary = error.summary
        return await self._finish_update(record, failed_at)

    async def set_disposition(
        self,
        event_id: UUID,
        disposition: EventDisposition,
        changed_at: datetime,
        expected_version: int,
    ) -> StateTransitionResult:
        """Apply one allowed administrative disposition transition."""
        changed_at = normalize_utc(changed_at, field_name="changed_at")
        record = await self._get_record_for_update(event_id)
        guarded = _guard_version(record, event_id, expected_version)
        if guarded is not None:
            return guarded
        assert record is not None
        try:
            validate_event_disposition_transition(
                EventDisposition(record.disposition),
                disposition,
            )
        except InvalidLifecycleTransition:
            return _transition_result(
                event_id,
                StateTransitionOutcome.INVALID_STATE,
                record.version,
            )
        record.disposition = disposition.value
        return await self._finish_update(record, changed_at)

    async def release_claim(
        self,
        event_id: UUID,
        claim_token: UUID,
        expected_version: int,
        released_at: datetime,
        next_retry_at: datetime | None,
    ) -> StateTransitionResult:
        """Return interrupted scoring work to pending under claim guards."""
        released_at = normalize_utc(released_at, field_name="released_at")
        next_retry_at = _normalize_optional_utc(
            next_retry_at,
            field_name="next_retry_at",
        )
        record = await self._get_record_for_update(event_id)
        guarded = _guard_claim(record, event_id, claim_token, expected_version)
        if guarded is not None:
            return guarded
        assert record is not None
        record.scoring_status = ScoringStatus.PENDING.value
        record.score = None
        record.next_retry_at = next_retry_at
        _clear_claim(record)
        return await self._finish_update(record, released_at)

    async def _resolve_snapshot_id(self, snapshot: SnapshotIdentity) -> int:
        result = await self._session.execute(
            select(PriceSnapshotRecord.id).where(
                PriceSnapshotRecord.marketplace == snapshot.marketplace,
                PriceSnapshotRecord.external_id == snapshot.external_id,
                PriceSnapshotRecord.collected_at == snapshot.collected_at,
                PriceSnapshotRecord.price == snapshot.price,
                PriceSnapshotRecord.currency == snapshot.currency,
            )
        )
        snapshot_id = result.scalar_one_or_none()
        if snapshot_id is None:
            msg = (
                "Market event source snapshot is not persisted: "
                f"{snapshot.marketplace}/{snapshot.external_id} at "
                f"{snapshot.collected_at.isoformat()}."
            )
            raise ValueError(msg)
        return snapshot_id

    async def _find_conflicting_event(
        self,
        event: PriceDropMarketEvent,
        *,
        previous_snapshot_id: int,
        current_snapshot_id: int,
    ) -> PriceDropMarketEvent | None:
        predicates = (
            MarketEventRecord.identity_key == event.identity_key,
            MarketEventRecord.id == event.id,
            and_(
                MarketEventRecord.event_type == event.event_type.value,
                MarketEventRecord.previous_snapshot_id == previous_snapshot_id,
                MarketEventRecord.current_snapshot_id == current_snapshot_id,
            ),
        )
        for predicate in predicates:
            row = await self._get_event_row(self._event_query().where(predicate))
            if row is not None:
                return self._map_row(row)
        return None

    async def _get_record_for_update(
        self,
        event_id: UUID,
    ) -> MarketEventRecord | None:
        result = await self._session.execute(
            select(MarketEventRecord)
            .where(MarketEventRecord.id == event_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def _finish_update(
        self,
        record: MarketEventRecord,
        changed_at: datetime,
    ) -> StateTransitionResult:
        record.updated_at = max(record.updated_at, changed_at)
        record.version += 1
        await self._session.flush()
        return _transition_result(
            record.id,
            StateTransitionOutcome.APPLIED,
            record.version,
        )

    @staticmethod
    def _event_query() -> Select[EventRow]:
        return (
            select(MarketEventRecord, _PreviousSnapshot, _CurrentSnapshot)
            .join(
                _PreviousSnapshot,
                MarketEventRecord.previous_snapshot_id == _PreviousSnapshot.id,
            )
            .join(
                _CurrentSnapshot,
                MarketEventRecord.current_snapshot_id == _CurrentSnapshot.id,
            )
        )

    async def _get_event_row(
        self,
        statement: Select[EventRow],
    ) -> EventDatabaseRow | None:
        result = await self._session.execute(statement.limit(1))
        return result.one_or_none()

    @staticmethod
    def _map_row(row: EventDatabaseRow) -> PriceDropMarketEvent:
        return market_event_to_domain(row[0], row[1], row[2])


def _claimable_at(now: datetime) -> ColumnElement[bool]:
    return and_(
        MarketEventRecord.disposition.in_(_ELIGIBLE_DISPOSITIONS),
        or_(
            and_(
                MarketEventRecord.scoring_status == ScoringStatus.PENDING.value,
                or_(
                    MarketEventRecord.next_retry_at.is_(None),
                    MarketEventRecord.next_retry_at <= now,
                ),
            ),
            and_(
                MarketEventRecord.scoring_status == ScoringStatus.FAILED.value,
                MarketEventRecord.next_retry_at.is_not(None),
                MarketEventRecord.next_retry_at <= now,
            ),
        ),
    )


def _claim_order() -> tuple[Any, ...]:
    ready_at = func.coalesce(
        MarketEventRecord.next_retry_at,
        MarketEventRecord.created_at,
    )
    return (ready_at, MarketEventRecord.created_at, MarketEventRecord.id)


def _guard_claim(
    record: MarketEventRecord | None,
    event_id: UUID,
    claim_token: UUID,
    expected_version: int,
) -> StateTransitionResult | None:
    guarded = _guard_version(record, event_id, expected_version)
    if guarded is not None:
        return guarded
    assert record is not None
    if (
        record.scoring_status != ScoringStatus.IN_PROGRESS.value
        or record.claim_token is None
    ):
        return _transition_result(
            event_id,
            StateTransitionOutcome.INVALID_STATE,
            record.version,
        )
    if record.claim_token != claim_token:
        return _transition_result(
            event_id,
            StateTransitionOutcome.CLAIM_LOST,
            record.version,
        )
    return None


def _guard_version(
    record: MarketEventRecord | None,
    event_id: UUID,
    expected_version: int,
) -> StateTransitionResult | None:
    if record is None:
        return _transition_result(
            event_id,
            StateTransitionOutcome.NOT_FOUND,
            None,
        )
    if record.version != expected_version:
        return _transition_result(
            event_id,
            StateTransitionOutcome.VERSION_CONFLICT,
            record.version,
        )
    return None


def _clear_claim(record: MarketEventRecord) -> None:
    record.claim_token = None
    record.worker_id = None
    record.claimed_at = None
    record.lease_expires_at = None


def _clear_error(record: MarketEventRecord) -> None:
    record.last_error_code = None
    record.last_error_summary = None


def _validate_claim_request(
    now: datetime,
    lease_until: datetime,
    worker_id: str,
) -> tuple[datetime, datetime, str]:
    now = normalize_utc(now, field_name="now")
    lease_until = normalize_utc(lease_until, field_name="lease_until")
    worker_id = worker_id.strip()
    if not worker_id:
        msg = "Worker ID must not be empty."
        raise ValueError(msg)
    if lease_until <= now:
        msg = "Lease expiry must be later than claim time."
        raise ValueError(msg)
    return now, lease_until, worker_id


def _validate_limit(limit: int) -> None:
    if limit < 0:
        msg = "Repository limit must not be negative."
        raise ValueError(msg)


def _normalize_optional_utc(
    value: datetime | None,
    *,
    field_name: str,
) -> datetime | None:
    return normalize_utc(value, field_name=field_name) if value is not None else None


def _transition_result(
    event_id: UUID,
    outcome: StateTransitionOutcome,
    version: int | None,
) -> StateTransitionResult:
    return StateTransitionResult(
        entity_id=event_id,
        outcome=outcome,
        version=version,
    )
