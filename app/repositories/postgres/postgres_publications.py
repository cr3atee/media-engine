from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.domain.identity import normalize_utc
from app.domain.lifecycle import (
    InvalidLifecycleTransition,
    PublicationStatus,
    validate_publication_status_transition,
)
from app.domain.processing import (
    IdempotentCreateStatus,
    ProcessingError,
    StateTransitionOutcome,
    StateTransitionResult,
    WorkClaim,
)
from app.domain.publications import (
    ClaimedPublication,
    CreatePublication,
    Publication,
    PublicationCreateResult,
)
from app.models.publication_record import PublicationRecord
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.publications import PublicationRepository

type ClaimTokenFactory = Callable[[], UUID]

_EXPIRED_PUBLICATION_ERROR = ProcessingError(
    code="lease_expired_ambiguous",
    summary="Publication claim expired before delivery was confirmed.",
)


class PostgresPublicationRepository(PublicationRepository):
    """PostgreSQL persistence for channel-neutral publication lifecycles."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        claim_token_factory: ClaimTokenFactory = uuid4,
    ) -> None:
        """Bind the repository to a caller-owned session and transaction."""
        self._session = session
        self._claim_token_factory = claim_token_factory

    async def create_idempotently(
        self,
        command: CreatePublication,
    ) -> PublicationCreateResult:
        """Race-safely create one logical delivery intent."""
        statement = (
            insert(PublicationRecord)
            .values(_publication_values(command))
            .on_conflict_do_nothing()
            .returning(PublicationRecord.id)
        )
        result = await self._session.execute(statement)
        inserted_id = result.scalar_one_or_none()
        if inserted_id is not None:
            stored = await self.get_by_id(inserted_id)
            assert stored is not None
            return PublicationCreateResult(stored, IdempotentCreateStatus.CREATED)

        existing = await self.get_by_idempotency_key(command.idempotency_key)
        if existing is not None:
            return PublicationCreateResult(existing, IdempotentCreateStatus.EXISTING)
        conflict = await self._find_identity_conflict(command)
        if conflict is not None:
            msg = (
                "Publication conflicts with an existing technical or logical "
                f"identity: {command.idempotency_key}."
            )
            raise RepositoryIdentityConflictError(msg)
        msg = f"Publication could not be created: {command.idempotency_key}."
        raise RepositoryIdentityConflictError(msg)

    async def get_by_id(self, publication_id: UUID) -> Publication | None:
        """Return one publication by technical identifier."""
        record = await self._get_record(publication_id)
        return _to_domain(record) if record is not None else None

    async def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> Publication | None:
        """Return one publication by deterministic delivery identity."""
        result = await self._session.execute(
            select(PublicationRecord).where(
                PublicationRecord.idempotency_key == idempotency_key
            )
        )
        record = result.scalar_one_or_none()
        return _to_domain(record) if record is not None else None

    async def list_for_event(self, event_id: UUID) -> Sequence[Publication]:
        """List publications in deterministic delivery readiness order."""
        result = await self._session.execute(
            select(PublicationRecord)
            .where(PublicationRecord.event_id == event_id)
            .order_by(*_publication_order())
        )
        return tuple(_to_domain(record) for record in result.scalars())

    async def list_pending(
        self,
        now: datetime,
        limit: int,
    ) -> Sequence[Publication]:
        """List due pending or known-failure retry work."""
        now = normalize_utc(now, field_name="now")
        _validate_limit(limit)
        if limit == 0:
            return ()
        result = await self._session.execute(
            select(PublicationRecord)
            .where(_claimable(now))
            .order_by(*_publication_order())
            .limit(limit)
        )
        return tuple(_to_domain(record) for record in result.scalars())

    async def claim_pending(
        self,
        now: datetime,
        worker_id: str,
        lease_until: datetime,
        limit: int,
    ) -> Sequence[ClaimedPublication]:
        """Claim due delivery intents with ``FOR UPDATE SKIP LOCKED``."""
        now, lease_until, worker_id = _validate_claim_request(
            now,
            lease_until,
            worker_id,
        )
        _validate_limit(limit)
        await self._mark_expired_claims_ambiguous(now)
        if limit == 0:
            return ()
        result = await self._session.execute(
            select(PublicationRecord)
            .where(_claimable(now))
            .order_by(*_publication_order())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        claimed: list[ClaimedPublication] = []
        for record in result.scalars():
            status = PublicationStatus(record.publication_status)
            if status is PublicationStatus.FAILED:
                validate_publication_status_transition(
                    status,
                    PublicationStatus.PENDING,
                )
                status = PublicationStatus.PENDING
            validate_publication_status_transition(
                status,
                PublicationStatus.IN_PROGRESS,
            )
            next_version = record.version + 1
            token = self._claim_token_factory()
            record.publication_status = PublicationStatus.IN_PROGRESS.value
            record.attempt_count += 1
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
            claimed.append(
                ClaimedPublication(publication=_to_domain(record), claim=claim)
            )
        await self._session.flush()
        return tuple(claimed)

    async def list_expired_claims(
        self,
        now: datetime,
        limit: int,
    ) -> Sequence[ClaimedPublication]:
        """Lock expired publication claims for explicit recovery."""
        now = normalize_utc(now, field_name="now")
        _validate_limit(limit)
        if limit == 0:
            return ()
        result = await self._session.execute(
            select(PublicationRecord)
            .where(
                PublicationRecord.publication_status
                == PublicationStatus.IN_PROGRESS.value,
                PublicationRecord.lease_expires_at <= now,
            )
            .order_by(
                PublicationRecord.lease_expires_at,
                PublicationRecord.created_at,
                PublicationRecord.id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return tuple(
            ClaimedPublication(publication=_to_domain(record), claim=_claim(record))
            for record in result.scalars()
        )

    async def mark_published(
        self,
        publication_id: UUID,
        claim_token: UUID,
        expected_version: int,
        external_message_id: str,
        published_at: datetime,
    ) -> StateTransitionResult:
        """Persist confirmed delivery with exact duplicate success handling."""
        published_at = normalize_utc(published_at, field_name="published_at")
        external_message_id = external_message_id.strip()
        if not external_message_id:
            msg = "External message ID must not be empty."
            raise ValueError(msg)
        record = await self._get_record_for_update(publication_id)
        if (
            record is not None
            and record.publication_status == PublicationStatus.PUBLISHED.value
        ):
            if record.external_message_id == external_message_id:
                return _transition_result(
                    publication_id,
                    StateTransitionOutcome.APPLIED,
                    record.version,
                )
            return _transition_result(
                publication_id,
                StateTransitionOutcome.INVALID_STATE,
                record.version,
            )
        guarded = _guard_claim(record, publication_id, claim_token, expected_version)
        if guarded is not None:
            return guarded
        assert record is not None
        validate_publication_status_transition(
            PublicationStatus(record.publication_status),
            PublicationStatus.PUBLISHED,
        )
        record.publication_status = PublicationStatus.PUBLISHED.value
        record.external_message_id = external_message_id
        record.published_at = published_at
        record.next_retry_at = None
        _clear_claim(record)
        _clear_error(record)
        return await self._finish_update(record, published_at)

    async def mark_failed(
        self,
        publication_id: UUID,
        claim_token: UUID,
        expected_version: int,
        error: ProcessingError,
        failed_at: datetime,
        next_retry_at: datetime | None,
    ) -> StateTransitionResult:
        """Persist a known delivery failure and optional retry eligibility."""
        failed_at = normalize_utc(failed_at, field_name="failed_at")
        next_retry_at = _normalize_optional_utc(next_retry_at, "next_retry_at")
        record = await self._get_record_for_update(publication_id)
        guarded = _guard_claim(record, publication_id, claim_token, expected_version)
        if guarded is not None:
            return guarded
        assert record is not None
        validate_publication_status_transition(
            PublicationStatus(record.publication_status),
            PublicationStatus.FAILED,
        )
        record.publication_status = PublicationStatus.FAILED.value
        record.next_retry_at = next_retry_at
        _clear_claim(record)
        record.last_error_code = error.code
        record.last_error_summary = error.summary
        return await self._finish_update(record, failed_at)

    async def mark_ambiguous(
        self,
        publication_id: UUID,
        claim_token: UUID,
        expected_version: int,
        error: ProcessingError,
        changed_at: datetime,
    ) -> StateTransitionResult:
        """Persist an unknown delivery outcome and block automatic resend."""
        changed_at = normalize_utc(changed_at, field_name="changed_at")
        record = await self._get_record_for_update(publication_id)
        guarded = _guard_claim(record, publication_id, claim_token, expected_version)
        if guarded is not None:
            return guarded
        assert record is not None
        validate_publication_status_transition(
            PublicationStatus(record.publication_status),
            PublicationStatus.AMBIGUOUS,
        )
        record.publication_status = PublicationStatus.AMBIGUOUS.value
        record.next_retry_at = None
        _clear_claim(record)
        record.last_error_code = error.code
        record.last_error_summary = error.summary
        return await self._finish_update(record, changed_at)

    async def cancel(
        self,
        publication_id: UUID,
        changed_at: datetime,
        expected_version: int,
    ) -> StateTransitionResult:
        """Cancel an eligible unpublished delivery."""
        changed_at = normalize_utc(changed_at, field_name="changed_at")
        record = await self._get_record_for_update(publication_id)
        guarded = _guard_version(record, publication_id, expected_version)
        if guarded is not None:
            return guarded
        assert record is not None
        try:
            validate_publication_status_transition(
                PublicationStatus(record.publication_status),
                PublicationStatus.CANCELLED,
            )
        except InvalidLifecycleTransition:
            return _transition_result(
                publication_id,
                StateTransitionOutcome.INVALID_STATE,
                record.version,
            )
        record.publication_status = PublicationStatus.CANCELLED.value
        record.next_retry_at = None
        _clear_claim(record)
        return await self._finish_update(record, changed_at)

    async def _find_identity_conflict(
        self,
        command: CreatePublication,
    ) -> PublicationRecord | None:
        result = await self._session.execute(
            select(PublicationRecord)
            .where(
                or_(
                    PublicationRecord.id == command.id,
                    (
                        (PublicationRecord.content_id == command.content_id)
                        & (PublicationRecord.channel == command.channel)
                        & (PublicationRecord.destination_key == command.destination_key)
                    ),
                )
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _mark_expired_claims_ambiguous(self, now: datetime) -> None:
        expired = await self.list_expired_claims(now, 1000)
        for claimed in expired:
            await self.mark_ambiguous(
                claimed.publication.id,
                claimed.claim.token,
                claimed.publication.version,
                _EXPIRED_PUBLICATION_ERROR,
                now,
            )

    async def _get_record(self, publication_id: UUID) -> PublicationRecord | None:
        return await self._session.get(PublicationRecord, publication_id)

    async def _get_record_for_update(
        self,
        publication_id: UUID,
    ) -> PublicationRecord | None:
        result = await self._session.execute(
            select(PublicationRecord)
            .where(PublicationRecord.id == publication_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def _finish_update(
        self,
        record: PublicationRecord,
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


def _publication_values(command: CreatePublication) -> dict[str, object]:
    return {
        "id": command.id,
        "event_id": command.event_id,
        "content_id": command.content_id,
        "channel": command.channel,
        "destination_key": command.destination_key,
        "publication_status": PublicationStatus.PENDING.value,
        "attempt_count": 0,
        "idempotency_key": command.idempotency_key,
        "external_message_id": None,
        "scheduled_at": command.scheduled_at,
        "next_retry_at": None,
        "published_at": None,
        "claim_token": None,
        "worker_id": None,
        "claimed_at": None,
        "lease_expires_at": None,
        "last_error_code": None,
        "last_error_summary": None,
        "created_at": command.created_at,
        "updated_at": command.created_at,
        "version": 1,
    }


def _to_domain(record: PublicationRecord) -> Publication:
    claim = _claim(record) if record.claim_token is not None else None
    error = (
        ProcessingError(
            code=record.last_error_code,
            summary=record.last_error_summary or "",
        )
        if record.last_error_code is not None
        else None
    )
    return Publication(
        id=record.id,
        event_id=record.event_id,
        content_id=record.content_id,
        channel=record.channel,
        destination_key=record.destination_key,
        idempotency_key=record.idempotency_key,
        status=PublicationStatus(record.publication_status),
        attempt_count=record.attempt_count,
        external_message_id=record.external_message_id,
        scheduled_at=record.scheduled_at,
        next_retry_at=record.next_retry_at,
        published_at=record.published_at,
        claim=claim,
        last_error=error,
        created_at=record.created_at,
        updated_at=record.updated_at,
        version=record.version,
    )


def _claim(record: PublicationRecord) -> WorkClaim:
    assert record.claim_token is not None
    assert record.worker_id is not None
    assert record.claimed_at is not None
    assert record.lease_expires_at is not None
    return WorkClaim(
        token=record.claim_token,
        worker_id=record.worker_id,
        claimed_at=record.claimed_at,
        lease_expires_at=record.lease_expires_at,
        version=record.version,
    )


def _claimable(now: datetime) -> ColumnElement[bool]:
    scheduled = or_(
        PublicationRecord.scheduled_at.is_(None),
        PublicationRecord.scheduled_at <= now,
    )
    return scheduled & or_(
        (
            (PublicationRecord.publication_status == PublicationStatus.PENDING.value)
            & or_(
                PublicationRecord.next_retry_at.is_(None),
                PublicationRecord.next_retry_at <= now,
            )
        ),
        (
            (PublicationRecord.publication_status == PublicationStatus.FAILED.value)
            & PublicationRecord.next_retry_at.is_not(None)
            & (PublicationRecord.next_retry_at <= now)
        ),
    )


def _publication_order() -> tuple[Any, ...]:
    ready_at = func.coalesce(
        PublicationRecord.next_retry_at,
        PublicationRecord.scheduled_at,
        PublicationRecord.created_at,
    )
    return (ready_at, PublicationRecord.created_at, PublicationRecord.id)


def _guard_claim(
    record: PublicationRecord | None,
    publication_id: UUID,
    claim_token: UUID,
    expected_version: int,
) -> StateTransitionResult | None:
    guarded = _guard_version(record, publication_id, expected_version)
    if guarded is not None:
        return guarded
    assert record is not None
    if (
        record.publication_status != PublicationStatus.IN_PROGRESS.value
        or record.claim_token is None
    ):
        return _transition_result(
            publication_id,
            StateTransitionOutcome.INVALID_STATE,
            record.version,
        )
    if record.claim_token != claim_token:
        return _transition_result(
            publication_id,
            StateTransitionOutcome.CLAIM_LOST,
            record.version,
        )
    return None


def _guard_version(
    record: PublicationRecord | None,
    publication_id: UUID,
    expected_version: int,
) -> StateTransitionResult | None:
    if record is None:
        return _transition_result(
            publication_id,
            StateTransitionOutcome.NOT_FOUND,
            None,
        )
    if record.version != expected_version:
        return _transition_result(
            publication_id,
            StateTransitionOutcome.VERSION_CONFLICT,
            record.version,
        )
    return None


def _clear_claim(record: PublicationRecord) -> None:
    record.claim_token = None
    record.worker_id = None
    record.claimed_at = None
    record.lease_expires_at = None


def _clear_error(record: PublicationRecord) -> None:
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


def _normalize_optional_utc(value: datetime | None, field_name: str) -> datetime | None:
    return normalize_utc(value, field_name=field_name) if value is not None else None


def _transition_result(
    publication_id: UUID,
    outcome: StateTransitionOutcome,
    version: int | None,
) -> StateTransitionResult:
    return StateTransitionResult(publication_id, outcome, version)
