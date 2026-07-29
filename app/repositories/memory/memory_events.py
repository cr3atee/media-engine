from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime
from uuid import UUID, uuid4

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
)
from app.domain.processing import (
    IdempotentCreateStatus,
    ProcessingError,
    StateTransitionOutcome,
    StateTransitionResult,
    WorkClaim,
)
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.events import MarketEventRepository

type ClaimTokenFactory = Callable[[], UUID]

_ELIGIBLE_DISPOSITIONS = frozenset(
    {EventDisposition.ACTIVE, EventDisposition.APPROVED},
)


class MemoryMarketEventRepository(MarketEventRepository):
    """Deterministic in-memory persistence for market-event lifecycles."""

    def __init__(
        self,
        *,
        claim_token_factory: ClaimTokenFactory = uuid4,
    ) -> None:
        """Initialize isolated storage and an injectable claim-token source."""
        self._events_by_id: dict[UUID, PriceDropMarketEvent] = {}
        self._event_ids_by_identity: dict[str, UUID] = {}
        self._claim_token_factory = claim_token_factory

    async def add_idempotently(
        self,
        candidate: MarketEventCandidate,
    ) -> EventAddResult:
        """Persist one event per deterministic identity without merging facts."""
        event = candidate.event
        existing_id = self._event_ids_by_identity.get(event.identity_key)
        if existing_id is not None:
            existing = self._events_by_id[existing_id]
            if _immutable_event_signature(existing) != _immutable_event_signature(
                event,
            ):
                msg = (
                    "Market event identity conflicts with immutable event data: "
                    f"{event.identity_key}."
                )
                raise RepositoryIdentityConflictError(msg)
            return EventAddResult(
                event=existing,
                status=IdempotentCreateStatus.EXISTING,
            )

        existing_by_id = self._events_by_id.get(event.id)
        if existing_by_id is not None:
            msg = (
                "Market event ID already belongs to identity "
                f"{existing_by_id.identity_key}."
            )
            raise RepositoryIdentityConflictError(msg)

        self._store(event)
        return EventAddResult(
            event=event,
            status=IdempotentCreateStatus.CREATED,
        )

    async def get_by_id(self, event_id: UUID) -> PriceDropMarketEvent | None:
        """Return one immutable event snapshot by technical identifier."""
        return self._events_by_id.get(event_id)

    async def get_by_identity(
        self,
        identity_key: str,
    ) -> PriceDropMarketEvent | None:
        """Return one immutable event snapshot by deterministic identity."""
        event_id = self._event_ids_by_identity.get(identity_key)
        return self._events_by_id.get(event_id) if event_id is not None else None

    async def list_pending(
        self,
        now: datetime,
        limit: int,
    ) -> Sequence[PriceDropMarketEvent]:
        """List eligible scoring work by readiness, creation time, and ID."""
        now = normalize_utc(now, field_name="now")
        _validate_limit(limit)
        eligible = (
            event
            for event in self._events_by_id.values()
            if _is_event_claimable(event, now)
        )
        return tuple(sorted(eligible, key=_event_processing_order)[:limit])

    async def claim_pending(
        self,
        now: datetime,
        worker_id: str,
        lease_until: datetime,
        limit: int,
    ) -> Sequence[ClaimedMarketEvent]:
        """Claim eligible events, replacing only claims whose lease expired."""
        now, lease_until, worker_id = _validate_claim_request(
            now,
            lease_until,
            worker_id,
        )
        _validate_limit(limit)
        eligible = sorted(
            (
                event
                for event in self._events_by_id.values()
                if _is_event_claimable(event, now)
            ),
            key=_event_processing_order,
        )[:limit]
        claimed: list[ClaimedMarketEvent] = []

        for event in eligible:
            if event.scoring_status is ScoringStatus.PENDING:
                validate_scoring_status_transition(
                    ScoringStatus.PENDING,
                    ScoringStatus.IN_PROGRESS,
                )
            elif event.scoring_status is ScoringStatus.FAILED:
                validate_scoring_status_transition(
                    ScoringStatus.FAILED,
                    ScoringStatus.PENDING,
                )
                validate_scoring_status_transition(
                    ScoringStatus.PENDING,
                    ScoringStatus.IN_PROGRESS,
                )

            next_version = event.version + 1
            claim = WorkClaim(
                token=self._claim_token_factory(),
                worker_id=worker_id,
                claimed_at=now,
                lease_expires_at=lease_until,
                version=next_version,
            )
            updated = replace(
                event,
                scoring_status=ScoringStatus.IN_PROGRESS,
                scoring_attempt_count=event.scoring_attempt_count + 1,
                next_retry_at=None,
                claim=claim,
                last_error=None,
                version=next_version,
            )
            self._store(updated)
            claimed.append(ClaimedMarketEvent(event=updated, claim=claim))

        return tuple(claimed)

    async def mark_scored(
        self,
        event_id: UUID,
        claim_token: UUID,
        expected_version: int,
        score: int,
        completed_at: datetime,
    ) -> StateTransitionResult:
        """Persist a score when both the claim token and version still match."""
        normalize_utc(completed_at, field_name="completed_at")
        event = self._events_by_id.get(event_id)
        guarded = _guard_event_claim(event_id, event, claim_token, expected_version)
        if guarded is not None:
            return guarded
        assert event is not None
        validate_scoring_status_transition(
            event.scoring_status,
            ScoringStatus.SUCCEEDED,
        )
        updated = replace(
            event,
            scoring_status=ScoringStatus.SUCCEEDED,
            score=score,
            next_retry_at=None,
            claim=None,
            last_error=None,
            version=event.version + 1,
        )
        self._store(updated)
        return _applied(updated.id, updated.version)

    async def mark_scoring_failed(
        self,
        event_id: UUID,
        claim_token: UUID,
        expected_version: int,
        error: ProcessingError,
        next_retry_at: datetime | None,
    ) -> StateTransitionResult:
        """Persist a known scoring failure and optional retry time."""
        next_retry_at = _normalize_optional_utc(
            next_retry_at,
            field_name="next_retry_at",
        )
        event = self._events_by_id.get(event_id)
        guarded = _guard_event_claim(event_id, event, claim_token, expected_version)
        if guarded is not None:
            return guarded
        assert event is not None
        validate_scoring_status_transition(
            event.scoring_status,
            ScoringStatus.FAILED,
        )
        updated = replace(
            event,
            scoring_status=ScoringStatus.FAILED,
            score=None,
            next_retry_at=next_retry_at,
            claim=None,
            last_error=error,
            version=event.version + 1,
        )
        self._store(updated)
        return _applied(updated.id, updated.version)

    async def set_disposition(
        self,
        event_id: UUID,
        disposition: EventDisposition,
        changed_at: datetime,
        expected_version: int,
    ) -> StateTransitionResult:
        """Apply an allowed administrative disposition transition."""
        normalize_utc(changed_at, field_name="changed_at")
        event = self._events_by_id.get(event_id)
        guarded = _guard_version(event_id, event, expected_version)
        if guarded is not None:
            return guarded
        assert event is not None
        try:
            validate_event_disposition_transition(event.disposition, disposition)
        except InvalidLifecycleTransition:
            return _transition_result(
                event.id,
                StateTransitionOutcome.INVALID_STATE,
                event.version,
            )
        updated = replace(
            event,
            disposition=disposition,
            version=event.version + 1,
        )
        self._store(updated)
        return _applied(updated.id, updated.version)

    async def release_claim(
        self,
        event_id: UUID,
        claim_token: UUID,
        expected_version: int,
        released_at: datetime,
        next_retry_at: datetime | None,
    ) -> StateTransitionResult:
        """Return interrupted scoring work to pending with a guarded update."""
        normalize_utc(released_at, field_name="released_at")
        next_retry_at = _normalize_optional_utc(
            next_retry_at,
            field_name="next_retry_at",
        )
        event = self._events_by_id.get(event_id)
        guarded = _guard_event_claim(event_id, event, claim_token, expected_version)
        if guarded is not None:
            return guarded
        assert event is not None
        updated = replace(
            event,
            scoring_status=ScoringStatus.PENDING,
            score=None,
            next_retry_at=next_retry_at,
            claim=None,
            version=event.version + 1,
        )
        self._store(updated)
        return _applied(updated.id, updated.version)

    def _store(self, event: PriceDropMarketEvent) -> None:
        self._events_by_id[event.id] = event
        self._event_ids_by_identity[event.identity_key] = event.id


def _immutable_event_signature(event: PriceDropMarketEvent) -> tuple[object, ...]:
    return (
        event.identity_key,
        event.identity_version,
        event.event_type,
        event.marketplace,
        event.external_id,
        event.canonical_product_id,
        event.occurred_at,
        event.detected_at,
        event.payload,
    )


def _is_event_claimable(event: PriceDropMarketEvent, now: datetime) -> bool:
    if event.disposition not in _ELIGIBLE_DISPOSITIONS:
        return False
    if event.scoring_status is ScoringStatus.PENDING:
        return event.next_retry_at is None or event.next_retry_at <= now
    if event.scoring_status is ScoringStatus.FAILED:
        return event.next_retry_at is not None and event.next_retry_at <= now
    if event.scoring_status is ScoringStatus.IN_PROGRESS:
        return event.claim is not None and event.claim.lease_expires_at <= now
    return False


def _event_processing_order(
    event: PriceDropMarketEvent,
) -> tuple[datetime, datetime, str]:
    if event.scoring_status is ScoringStatus.IN_PROGRESS and event.claim is not None:
        ready_at = event.claim.lease_expires_at
    else:
        ready_at = event.next_retry_at or event.created_at
    return (ready_at, event.created_at, event.id.hex)


def _guard_event_claim(
    event_id: UUID,
    event: PriceDropMarketEvent | None,
    claim_token: UUID,
    expected_version: int,
) -> StateTransitionResult | None:
    guarded = _guard_version(event_id, event, expected_version)
    if guarded is not None:
        return guarded
    assert event is not None
    if event.scoring_status is not ScoringStatus.IN_PROGRESS or event.claim is None:
        return _transition_result(
            event.id,
            StateTransitionOutcome.INVALID_STATE,
            event.version,
        )
    if event.claim.token != claim_token:
        return _transition_result(
            event.id,
            StateTransitionOutcome.CLAIM_LOST,
            event.version,
        )
    return None


def _guard_version(
    entity_id: UUID,
    event: PriceDropMarketEvent | None,
    expected_version: int,
) -> StateTransitionResult | None:
    if event is None:
        return _transition_result(
            entity_id,
            StateTransitionOutcome.NOT_FOUND,
            None,
        )
    if event.version != expected_version:
        return _transition_result(
            entity_id,
            StateTransitionOutcome.VERSION_CONFLICT,
            event.version,
        )
    return None


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


def _applied(entity_id: UUID, version: int) -> StateTransitionResult:
    return _transition_result(entity_id, StateTransitionOutcome.APPLIED, version)


def _transition_result(
    entity_id: UUID,
    outcome: StateTransitionOutcome,
    version: int | None,
) -> StateTransitionResult:
    return StateTransitionResult(entity_id=entity_id, outcome=outcome, version=version)
