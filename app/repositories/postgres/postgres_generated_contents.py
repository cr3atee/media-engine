from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.generated_content import (
    ClaimedContentAttempt,
    ContentCreateResult,
    ContentOrigin,
    CreateContentAttempt,
    GeneratedContentAttempt,
    calculate_content_checksum,
)
from app.domain.identity import normalize_utc
from app.domain.lifecycle import (
    ContentGenerationStatus,
    ContentReviewStatus,
    InvalidLifecycleTransition,
    validate_content_generation_status_transition,
    validate_content_review_status_transition,
)
from app.domain.processing import (
    IdempotentCreateStatus,
    ProcessingError,
    StateTransitionOutcome,
    StateTransitionResult,
    WorkClaim,
)
from app.models.generated_content_record import GeneratedContentRecord
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.generated_contents import GeneratedContentRepository

type ClaimTokenFactory = Callable[[], UUID]

_ACTIVE_STATUSES = (
    ContentGenerationStatus.PENDING.value,
    ContentGenerationStatus.IN_PROGRESS.value,
)
_EXPIRED_CONTENT_ERROR = ProcessingError(
    code="lease_expired_abandoned",
    summary="Content-generation claim expired before completion.",
)


class PostgresGeneratedContentRepository(GeneratedContentRepository):
    """PostgreSQL persistence for immutable generated-content attempts."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        claim_token_factory: ClaimTokenFactory = uuid4,
    ) -> None:
        """Bind the repository to a caller-owned session and transaction."""
        self._session = session
        self._claim_token_factory = claim_token_factory

    async def create_attempt(
        self,
        command: CreateContentAttempt,
    ) -> ContentCreateResult:
        """Race-safely create one immutable generation attempt."""
        if command.origin is ContentOrigin.HUMAN_EDIT:
            msg = (
                "CreateContentAttempt cannot represent completed human-edited text; "
                "human revision creation belongs to the administrative service."
            )
            raise ValueError(msg)
        await self._validate_parent(command)
        statement = (
            insert(GeneratedContentRecord)
            .values(_content_values(command))
            .on_conflict_do_nothing()
            .returning(GeneratedContentRecord.id)
        )
        result = await self._session.execute(statement)
        inserted_id = result.scalar_one_or_none()
        if inserted_id is not None:
            stored = await self.get_by_id(inserted_id)
            assert stored is not None
            return ContentCreateResult(stored, IdempotentCreateStatus.CREATED)

        existing = await self._get_by_key(command.idempotency_key)
        if existing is not None:
            if _content_signature(existing) != _command_signature(command):
                msg = (
                    "Content attempt identity conflicts with immutable metadata: "
                    f"{command.idempotency_key}."
                )
                raise RepositoryIdentityConflictError(msg)
            return ContentCreateResult(existing, IdempotentCreateStatus.EXISTING)

        conflict = await self._find_identity_conflict(command)
        if conflict is not None:
            msg = (
                "Content attempt conflicts with an existing technical or active "
                f"identity: {command.idempotency_key}."
            )
            raise RepositoryIdentityConflictError(msg)
        msg = f"Content attempt could not be created: {command.idempotency_key}."
        raise RepositoryIdentityConflictError(msg)

    async def get_by_id(
        self,
        content_id: UUID,
    ) -> GeneratedContentAttempt | None:
        """Return one immutable content attempt by identifier."""
        record = await self._get_record(content_id)
        return _to_domain(record) if record is not None else None

    async def list_for_event(
        self,
        event_id: UUID,
    ) -> Sequence[GeneratedContentAttempt]:
        """List an event's content attempts in deterministic revision order."""
        result = await self._session.execute(
            select(GeneratedContentRecord)
            .where(GeneratedContentRecord.event_id == event_id)
            .order_by(
                GeneratedContentRecord.attempt_number,
                GeneratedContentRecord.created_at,
                GeneratedContentRecord.id,
            )
        )
        return tuple(_to_domain(record) for record in result.scalars())

    async def get_latest_revision(
        self,
        event_id: UUID,
        content_type: str,
        language: str,
    ) -> GeneratedContentAttempt | None:
        """Return the highest ordered revision for an event and format."""
        content_type = _normalize_selector(content_type, "content_type")
        language = _normalize_selector(language, "language")
        result = await self._session.execute(
            select(GeneratedContentRecord)
            .where(
                GeneratedContentRecord.event_id == event_id,
                GeneratedContentRecord.content_type == content_type,
                GeneratedContentRecord.language == language,
            )
            .order_by(
                GeneratedContentRecord.attempt_number.desc(),
                GeneratedContentRecord.created_at.desc(),
                GeneratedContentRecord.id.desc(),
            )
            .limit(1)
        )
        record = result.scalar_one_or_none()
        return _to_domain(record) if record is not None else None

    async def claim_pending(
        self,
        now: datetime,
        worker_id: str,
        lease_until: datetime,
        limit: int,
    ) -> Sequence[ClaimedContentAttempt]:
        """Claim due attempts with ``FOR UPDATE SKIP LOCKED``."""
        now, lease_until, worker_id = _validate_claim_request(
            now,
            lease_until,
            worker_id,
        )
        _validate_limit(limit)
        await self._abandon_expired_claims(now)
        if limit == 0:
            return ()
        result = await self._session.execute(
            select(GeneratedContentRecord)
            .where(
                GeneratedContentRecord.generation_status
                == ContentGenerationStatus.PENDING.value,
                or_(
                    GeneratedContentRecord.next_retry_at.is_(None),
                    GeneratedContentRecord.next_retry_at <= now,
                ),
            )
            .order_by(
                GeneratedContentRecord.attempt_number,
                GeneratedContentRecord.created_at,
                GeneratedContentRecord.id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        claimed: list[ClaimedContentAttempt] = []
        for record in result.scalars():
            validate_content_generation_status_transition(
                ContentGenerationStatus(record.generation_status),
                ContentGenerationStatus.IN_PROGRESS,
            )
            next_version = record.version + 1
            token = self._claim_token_factory()
            record.generation_status = ContentGenerationStatus.IN_PROGRESS.value
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
                ClaimedContentAttempt(content=_to_domain(record), claim=claim)
            )
        await self._session.flush()
        return tuple(claimed)

    async def list_expired_claims(
        self,
        now: datetime,
        limit: int,
    ) -> Sequence[ClaimedContentAttempt]:
        """Lock expired generation claims for bounded explicit recovery."""
        now = normalize_utc(now, field_name="now")
        _validate_limit(limit)
        if limit == 0:
            return ()
        result = await self._session.execute(
            select(GeneratedContentRecord)
            .where(
                GeneratedContentRecord.generation_status
                == ContentGenerationStatus.IN_PROGRESS.value,
                GeneratedContentRecord.lease_expires_at <= now,
            )
            .order_by(
                GeneratedContentRecord.lease_expires_at,
                GeneratedContentRecord.created_at,
                GeneratedContentRecord.id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return tuple(
            ClaimedContentAttempt(content=_to_domain(record), claim=_claim(record))
            for record in result.scalars()
        )

    async def complete_attempt(
        self,
        content_id: UUID,
        claim_token: UUID,
        expected_version: int,
        content_text: str,
        content_checksum: str,
        completed_at: datetime,
    ) -> StateTransitionResult:
        """Persist generated text under claim and version guards."""
        completed_at = normalize_utc(completed_at, field_name="completed_at")
        if calculate_content_checksum(content_text) != content_checksum:
            msg = "Content checksum does not match content text."
            raise ValueError(msg)
        record = await self._get_record_for_update(content_id)
        guarded = _guard_claim(record, content_id, claim_token, expected_version)
        if guarded is not None:
            return guarded
        assert record is not None
        validate_content_generation_status_transition(
            ContentGenerationStatus(record.generation_status),
            ContentGenerationStatus.GENERATED,
        )
        record.generation_status = ContentGenerationStatus.GENERATED.value
        record.content_text = content_text
        record.content_checksum = content_checksum
        record.completed_at = completed_at
        record.next_retry_at = None
        _clear_claim(record)
        _clear_error(record)
        return await self._finish_update(record, completed_at)

    async def fail_attempt(
        self,
        content_id: UUID,
        claim_token: UUID,
        expected_version: int,
        error: ProcessingError,
        failed_at: datetime,
        next_retry_at: datetime | None,
    ) -> StateTransitionResult:
        """Persist one immutable failed attempt and retry eligibility."""
        failed_at = normalize_utc(failed_at, field_name="failed_at")
        next_retry_at = _normalize_optional_utc(next_retry_at, "next_retry_at")
        record = await self._get_record_for_update(content_id)
        guarded = _guard_claim(record, content_id, claim_token, expected_version)
        if guarded is not None:
            return guarded
        assert record is not None
        validate_content_generation_status_transition(
            ContentGenerationStatus(record.generation_status),
            ContentGenerationStatus.FAILED,
        )
        record.generation_status = ContentGenerationStatus.FAILED.value
        record.completed_at = failed_at
        record.next_retry_at = next_retry_at
        _clear_claim(record)
        record.last_error_code = error.code
        record.last_error_summary = error.summary
        return await self._finish_update(record, failed_at)

    async def set_review_status(
        self,
        content_id: UUID,
        review_status: ContentReviewStatus,
        changed_at: datetime,
        expected_version: int,
    ) -> StateTransitionResult:
        """Apply a guarded terminal review decision."""
        changed_at = normalize_utc(changed_at, field_name="changed_at")
        record = await self._get_record_for_update(content_id)
        guarded = _guard_version(record, content_id, expected_version)
        if guarded is not None:
            return guarded
        assert record is not None
        if record.generation_status != ContentGenerationStatus.GENERATED.value:
            return _transition_result(
                content_id,
                StateTransitionOutcome.INVALID_STATE,
                record.version,
            )
        try:
            validate_content_review_status_transition(
                ContentReviewStatus(record.review_status),
                review_status,
            )
        except InvalidLifecycleTransition:
            return _transition_result(
                content_id,
                StateTransitionOutcome.INVALID_STATE,
                record.version,
            )
        record.review_status = review_status.value
        return await self._finish_update(record, changed_at)

    async def release_claim(
        self,
        content_id: UUID,
        claim_token: UUID,
        expected_version: int,
        released_at: datetime,
    ) -> StateTransitionResult:
        """Abandon an expired generation attempt under claim guards."""
        released_at = normalize_utc(released_at, field_name="released_at")
        record = await self._get_record_for_update(content_id)
        guarded = _guard_claim(record, content_id, claim_token, expected_version)
        if guarded is not None:
            return guarded
        assert record is not None
        validate_content_generation_status_transition(
            ContentGenerationStatus(record.generation_status),
            ContentGenerationStatus.ABANDONED,
        )
        record.generation_status = ContentGenerationStatus.ABANDONED.value
        record.completed_at = released_at
        record.next_retry_at = None
        _clear_claim(record)
        record.last_error_code = _EXPIRED_CONTENT_ERROR.code
        record.last_error_summary = _EXPIRED_CONTENT_ERROR.summary
        return await self._finish_update(record, released_at)

    async def _validate_parent(self, command: CreateContentAttempt) -> None:
        if command.parent_content_id is None:
            return
        parent = await self._get_record(command.parent_content_id)
        if (
            parent is None
            or parent.event_id != command.event_id
            or parent.tenant_id != command.tenant_id
        ):
            msg = "Content parent must be an existing revision for the same event."
            raise RepositoryIdentityConflictError(msg)

    async def _get_by_key(self, key: str) -> GeneratedContentAttempt | None:
        result = await self._session.execute(
            select(GeneratedContentRecord).where(
                GeneratedContentRecord.idempotency_key == key
            )
        )
        record = result.scalar_one_or_none()
        return _to_domain(record) if record is not None else None

    async def _find_identity_conflict(
        self,
        command: CreateContentAttempt,
    ) -> GeneratedContentRecord | None:
        result = await self._session.execute(
            select(GeneratedContentRecord)
            .where(
                or_(
                    GeneratedContentRecord.id == command.id,
                    and_(
                        GeneratedContentRecord.tenant_id == command.tenant_id,
                        GeneratedContentRecord.event_id == command.event_id,
                        GeneratedContentRecord.content_type == command.content_type,
                        GeneratedContentRecord.language == command.language,
                        GeneratedContentRecord.prompt_version == command.prompt_version,
                        GeneratedContentRecord.generation_status.in_(_ACTIVE_STATUSES),
                    ),
                )
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _abandon_expired_claims(self, now: datetime) -> None:
        expired = await self.list_expired_claims(now, 1000)
        for claimed in expired:
            await self.release_claim(
                claimed.content.id,
                claimed.claim.token,
                claimed.content.version,
                now,
            )

    async def _get_record(self, content_id: UUID) -> GeneratedContentRecord | None:
        return await self._session.get(GeneratedContentRecord, content_id)

    async def _get_record_for_update(
        self,
        content_id: UUID,
    ) -> GeneratedContentRecord | None:
        result = await self._session.execute(
            select(GeneratedContentRecord)
            .where(GeneratedContentRecord.id == content_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def _finish_update(
        self,
        record: GeneratedContentRecord,
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


def _content_values(command: CreateContentAttempt) -> dict[str, object]:
    return {
        "id": command.id,
        "tenant_id": command.tenant_id,
        "event_id": command.event_id,
        "parent_content_id": command.parent_content_id,
        "content_type": command.content_type,
        "language": command.language,
        "origin": command.origin.value,
        "provider": command.provider,
        "model": command.model,
        "prompt_version": command.prompt_version,
        "content_text": None,
        "generation_status": ContentGenerationStatus.PENDING.value,
        "review_status": ContentReviewStatus.PENDING.value,
        "attempt_number": command.attempt_number,
        "idempotency_key": command.idempotency_key,
        "content_checksum": None,
        "next_retry_at": None,
        "claim_token": None,
        "worker_id": None,
        "claimed_at": None,
        "lease_expires_at": None,
        "last_error_code": None,
        "last_error_summary": None,
        "created_at": command.created_at,
        "updated_at": command.created_at,
        "completed_at": None,
        "version": 1,
    }


def _to_domain(record: GeneratedContentRecord) -> GeneratedContentAttempt:
    claim = _claim(record) if record.claim_token is not None else None
    error = (
        ProcessingError(
            code=record.last_error_code,
            summary=record.last_error_summary or "",
        )
        if record.last_error_code is not None
        else None
    )
    return GeneratedContentAttempt(
        id=record.id,
        tenant_id=record.tenant_id,
        event_id=record.event_id,
        parent_content_id=record.parent_content_id,
        content_type=record.content_type,
        language=record.language,
        origin=ContentOrigin(record.origin),
        provider=record.provider,
        model=record.model,
        prompt_version=record.prompt_version,
        content_text=record.content_text,
        generation_status=ContentGenerationStatus(record.generation_status),
        review_status=ContentReviewStatus(record.review_status),
        attempt_number=record.attempt_number,
        idempotency_key=record.idempotency_key,
        content_checksum=record.content_checksum,
        next_retry_at=record.next_retry_at,
        claim=claim,
        last_error=error,
        created_at=record.created_at,
        updated_at=record.updated_at,
        completed_at=record.completed_at,
        version=record.version,
    )


def _claim(record: GeneratedContentRecord) -> WorkClaim:
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


def _guard_claim(
    record: GeneratedContentRecord | None,
    content_id: UUID,
    claim_token: UUID,
    expected_version: int,
) -> StateTransitionResult | None:
    guarded = _guard_version(record, content_id, expected_version)
    if guarded is not None:
        return guarded
    assert record is not None
    if (
        record.generation_status != ContentGenerationStatus.IN_PROGRESS.value
        or record.claim_token is None
    ):
        return _transition_result(
            content_id,
            StateTransitionOutcome.INVALID_STATE,
            record.version,
        )
    if record.claim_token != claim_token:
        return _transition_result(
            content_id,
            StateTransitionOutcome.CLAIM_LOST,
            record.version,
        )
    return None


def _guard_version(
    record: GeneratedContentRecord | None,
    content_id: UUID,
    expected_version: int,
) -> StateTransitionResult | None:
    if record is None:
        return _transition_result(
            content_id,
            StateTransitionOutcome.NOT_FOUND,
            None,
        )
    if record.version != expected_version:
        return _transition_result(
            content_id,
            StateTransitionOutcome.VERSION_CONFLICT,
            record.version,
        )
    return None


def _clear_claim(record: GeneratedContentRecord) -> None:
    record.claim_token = None
    record.worker_id = None
    record.claimed_at = None
    record.lease_expires_at = None


def _clear_error(record: GeneratedContentRecord) -> None:
    record.last_error_code = None
    record.last_error_summary = None


def _command_signature(command: CreateContentAttempt) -> tuple[object, ...]:
    return (
        command.event_id,
        command.tenant_id,
        command.content_type,
        command.language,
        command.prompt_version,
        command.attempt_number,
        command.parent_content_id,
        command.origin,
        command.provider,
        command.model,
    )


def _content_signature(content: GeneratedContentAttempt) -> tuple[object, ...]:
    return (
        content.event_id,
        content.tenant_id,
        content.content_type,
        content.language,
        content.prompt_version,
        content.attempt_number,
        content.parent_content_id,
        content.origin,
        content.provider,
        content.model,
    )


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


def _normalize_selector(value: str, field_name: str) -> str:
    value = value.strip().lower()
    if not value:
        msg = f"{field_name} must not be empty."
        raise ValueError(msg)
    return value


def _normalize_optional_utc(value: datetime | None, field_name: str) -> datetime | None:
    return normalize_utc(value, field_name=field_name) if value is not None else None


def _transition_result(
    content_id: UUID,
    outcome: StateTransitionOutcome,
    version: int | None,
) -> StateTransitionResult:
    return StateTransitionResult(content_id, outcome, version)
