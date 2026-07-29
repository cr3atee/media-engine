from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime
from uuid import UUID, uuid4

from app.domain.generated_content import (
    ClaimedContentAttempt,
    ContentCreateResult,
    ContentOrigin,
    CreateContentAttempt,
    GeneratedContentAttempt,
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
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.generated_contents import GeneratedContentRepository

type ClaimTokenFactory = Callable[[], UUID]

_ACTIVE_GENERATION_STATUSES = frozenset(
    {ContentGenerationStatus.PENDING, ContentGenerationStatus.IN_PROGRESS},
)
_EXPIRED_CONTENT_ERROR = ProcessingError(
    code="lease_expired_abandoned",
    summary="Content-generation claim expired before completion.",
)


class MemoryGeneratedContentRepository(GeneratedContentRepository):
    """Deterministic in-memory persistence for immutable content attempts."""

    def __init__(
        self,
        *,
        claim_token_factory: ClaimTokenFactory = uuid4,
    ) -> None:
        """Initialize isolated storage and an injectable claim-token source."""
        self._contents_by_id: dict[UUID, GeneratedContentAttempt] = {}
        self._content_ids_by_key: dict[str, UUID] = {}
        self._claim_token_factory = claim_token_factory

    async def create_attempt(
        self,
        command: CreateContentAttempt,
    ) -> ContentCreateResult:
        """Create one AI attempt while preserving idempotency and history."""
        existing_id = self._content_ids_by_key.get(command.idempotency_key)
        if existing_id is not None:
            existing = self._contents_by_id[existing_id]
            if _content_command_signature(existing) != _command_signature(command):
                msg = (
                    "Content attempt identity conflicts with immutable metadata: "
                    f"{command.idempotency_key}."
                )
                raise RepositoryIdentityConflictError(msg)
            return ContentCreateResult(
                content=existing,
                status=IdempotentCreateStatus.EXISTING,
            )

        existing_by_id = self._contents_by_id.get(command.id)
        if existing_by_id is not None:
            msg = (
                "Content ID already belongs to idempotency key "
                f"{existing_by_id.idempotency_key}."
            )
            raise RepositoryIdentityConflictError(msg)

        if command.origin is ContentOrigin.HUMAN_EDIT:
            msg = (
                "CreateContentAttempt cannot represent completed human-edited text; "
                "human revision creation belongs to the administrative service."
            )
            raise ValueError(msg)

        if command.parent_content_id is not None:
            parent = self._contents_by_id.get(command.parent_content_id)
            if parent is None or parent.event_id != command.event_id:
                msg = "Content parent must be an existing revision for the same event."
                raise RepositoryIdentityConflictError(msg)

        for content in self._contents_by_id.values():
            if (
                _active_generation_identity(content)
                == _active_command_identity(command)
                and content.generation_status in _ACTIVE_GENERATION_STATUSES
            ):
                msg = (
                    "An active generation attempt already exists for this event, "
                    "format, language, and prompt version."
                )
                raise RepositoryIdentityConflictError(msg)

        content = GeneratedContentAttempt(
            id=command.id,
            event_id=command.event_id,
            parent_content_id=command.parent_content_id,
            content_type=command.content_type,
            language=command.language,
            origin=command.origin,
            provider=command.provider,
            model=command.model,
            prompt_version=command.prompt_version,
            generation_status=ContentGenerationStatus.PENDING,
            review_status=ContentReviewStatus.PENDING,
            attempt_number=command.attempt_number,
            idempotency_key=command.idempotency_key,
            created_at=command.created_at,
            updated_at=command.created_at,
        )
        self._store(content)
        return ContentCreateResult(
            content=content,
            status=IdempotentCreateStatus.CREATED,
        )

    async def get_by_id(
        self,
        content_id: UUID,
    ) -> GeneratedContentAttempt | None:
        """Return one immutable content-attempt snapshot."""
        return self._contents_by_id.get(content_id)

    async def list_for_event(
        self,
        event_id: UUID,
    ) -> Sequence[GeneratedContentAttempt]:
        """List one event's revisions by attempt, creation time, and ID."""
        return tuple(
            sorted(
                (
                    content
                    for content in self._contents_by_id.values()
                    if content.event_id == event_id
                ),
                key=_content_revision_order,
            ),
        )

    async def get_latest_revision(
        self,
        event_id: UUID,
        content_type: str,
        language: str,
    ) -> GeneratedContentAttempt | None:
        """Return the highest ordered revision for an event and format."""
        content_type = _normalize_selector(content_type, field_name="content_type")
        language = _normalize_selector(language, field_name="language")
        revisions = sorted(
            (
                content
                for content in self._contents_by_id.values()
                if content.event_id == event_id
                and content.content_type == content_type
                and content.language == language
            ),
            key=_content_revision_order,
        )
        return revisions[-1] if revisions else None

    async def claim_pending(
        self,
        now: datetime,
        worker_id: str,
        lease_until: datetime,
        limit: int,
    ) -> Sequence[ClaimedContentAttempt]:
        """Claim pending generation attempts without stealing active claims."""
        now, lease_until, worker_id = _validate_claim_request(
            now,
            lease_until,
            worker_id,
        )
        _validate_limit(limit)
        self._abandon_expired_claims(now)
        eligible = sorted(
            (
                content
                for content in self._contents_by_id.values()
                if content.generation_status is ContentGenerationStatus.PENDING
                and (content.next_retry_at is None or content.next_retry_at <= now)
            ),
            key=_content_revision_order,
        )[:limit]
        claimed: list[ClaimedContentAttempt] = []

        for content in eligible:
            validate_content_generation_status_transition(
                content.generation_status,
                ContentGenerationStatus.IN_PROGRESS,
            )
            next_version = content.version + 1
            claim = WorkClaim(
                token=self._claim_token_factory(),
                worker_id=worker_id,
                claimed_at=now,
                lease_expires_at=lease_until,
                version=next_version,
            )
            updated = replace(
                content,
                generation_status=ContentGenerationStatus.IN_PROGRESS,
                updated_at=now,
                next_retry_at=None,
                claim=claim,
                last_error=None,
                version=next_version,
            )
            self._store(updated)
            claimed.append(ClaimedContentAttempt(content=updated, claim=claim))

        return tuple(claimed)

    async def list_expired_claims(
        self,
        now: datetime,
        limit: int,
    ) -> Sequence[ClaimedContentAttempt]:
        """List expired generation claims without changing their state."""
        now = normalize_utc(now, field_name="now")
        _validate_limit(limit)
        expired = sorted(
            (
                content
                for content in self._contents_by_id.values()
                if content.generation_status is ContentGenerationStatus.IN_PROGRESS
                and content.claim is not None
                and content.claim.lease_expires_at <= now
            ),
            key=_expired_claim_order,
        )[:limit]
        return tuple(
            ClaimedContentAttempt(content=content, claim=content.claim)
            for content in expired
            if content.claim is not None
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
        """Complete a claimed attempt without mutating prior content bodies."""
        completed_at = normalize_utc(completed_at, field_name="completed_at")
        content = self._contents_by_id.get(content_id)
        guarded = _guard_content_claim(
            content_id,
            content,
            claim_token,
            expected_version,
        )
        if guarded is not None:
            return guarded
        assert content is not None
        validate_content_generation_status_transition(
            content.generation_status,
            ContentGenerationStatus.GENERATED,
        )
        updated = replace(
            content,
            generation_status=ContentGenerationStatus.GENERATED,
            content_text=content_text,
            content_checksum=content_checksum,
            updated_at=completed_at,
            completed_at=completed_at,
            next_retry_at=None,
            claim=None,
            last_error=None,
            version=content.version + 1,
        )
        self._store(updated)
        return _applied(updated.id, updated.version)

    async def fail_attempt(
        self,
        content_id: UUID,
        claim_token: UUID,
        expected_version: int,
        error: ProcessingError,
        failed_at: datetime,
        next_retry_at: datetime | None,
    ) -> StateTransitionResult:
        """Record one immutable failed attempt; retries use a new attempt row."""
        failed_at = normalize_utc(failed_at, field_name="failed_at")
        next_retry_at = _normalize_optional_utc(
            next_retry_at,
            field_name="next_retry_at",
        )
        content = self._contents_by_id.get(content_id)
        guarded = _guard_content_claim(
            content_id,
            content,
            claim_token,
            expected_version,
        )
        if guarded is not None:
            return guarded
        assert content is not None
        validate_content_generation_status_transition(
            content.generation_status,
            ContentGenerationStatus.FAILED,
        )
        updated = replace(
            content,
            generation_status=ContentGenerationStatus.FAILED,
            updated_at=failed_at,
            completed_at=failed_at,
            next_retry_at=next_retry_at,
            claim=None,
            last_error=error,
            version=content.version + 1,
        )
        self._store(updated)
        return _applied(updated.id, updated.version)

    async def set_review_status(
        self,
        content_id: UUID,
        review_status: ContentReviewStatus,
        changed_at: datetime,
        expected_version: int,
    ) -> StateTransitionResult:
        """Apply a terminal review decision to completed generated content."""
        changed_at = normalize_utc(changed_at, field_name="changed_at")
        content = self._contents_by_id.get(content_id)
        guarded = _guard_version(content_id, content, expected_version)
        if guarded is not None:
            return guarded
        assert content is not None
        if content.generation_status is not ContentGenerationStatus.GENERATED:
            return _transition_result(
                content.id,
                StateTransitionOutcome.INVALID_STATE,
                content.version,
            )
        try:
            validate_content_review_status_transition(
                content.review_status,
                review_status,
            )
        except InvalidLifecycleTransition:
            return _transition_result(
                content.id,
                StateTransitionOutcome.INVALID_STATE,
                content.version,
            )
        updated = replace(
            content,
            review_status=review_status,
            updated_at=changed_at,
            version=content.version + 1,
        )
        self._store(updated)
        return _applied(updated.id, updated.version)

    async def release_claim(
        self,
        content_id: UUID,
        claim_token: UUID,
        expected_version: int,
        released_at: datetime,
    ) -> StateTransitionResult:
        """Abandon an interrupted or expired content-generation attempt."""
        released_at = normalize_utc(released_at, field_name="released_at")
        content = self._contents_by_id.get(content_id)
        guarded = _guard_content_claim(
            content_id,
            content,
            claim_token,
            expected_version,
        )
        if guarded is not None:
            return guarded
        assert content is not None
        validate_content_generation_status_transition(
            content.generation_status,
            ContentGenerationStatus.ABANDONED,
        )
        updated = replace(
            content,
            generation_status=ContentGenerationStatus.ABANDONED,
            updated_at=released_at,
            completed_at=released_at,
            next_retry_at=None,
            claim=None,
            last_error=_EXPIRED_CONTENT_ERROR,
            version=content.version + 1,
        )
        self._store(updated)
        return _applied(updated.id, updated.version)

    def _abandon_expired_claims(self, now: datetime) -> None:
        expired = (
            content
            for content in tuple(self._contents_by_id.values())
            if content.generation_status is ContentGenerationStatus.IN_PROGRESS
            and content.claim is not None
            and content.claim.lease_expires_at <= now
        )
        for content in expired:
            validate_content_generation_status_transition(
                content.generation_status,
                ContentGenerationStatus.ABANDONED,
            )
            updated = replace(
                content,
                generation_status=ContentGenerationStatus.ABANDONED,
                updated_at=now,
                completed_at=now,
                next_retry_at=None,
                claim=None,
                last_error=_EXPIRED_CONTENT_ERROR,
                version=content.version + 1,
            )
            self._store(updated)

    def _store(self, content: GeneratedContentAttempt) -> None:
        self._contents_by_id[content.id] = content
        self._content_ids_by_key[content.idempotency_key] = content.id


def _command_signature(command: CreateContentAttempt) -> tuple[object, ...]:
    return (
        command.event_id,
        command.content_type,
        command.language,
        command.prompt_version,
        command.attempt_number,
        command.parent_content_id,
        command.origin,
        command.provider,
        command.model,
    )


def _content_command_signature(
    content: GeneratedContentAttempt,
) -> tuple[object, ...]:
    return (
        content.event_id,
        content.content_type,
        content.language,
        content.prompt_version,
        content.attempt_number,
        content.parent_content_id,
        content.origin,
        content.provider,
        content.model,
    )


def _active_command_identity(command: CreateContentAttempt) -> tuple[object, ...]:
    return (
        command.event_id,
        command.content_type,
        command.language,
        command.prompt_version,
    )


def _active_generation_identity(
    content: GeneratedContentAttempt,
) -> tuple[object, ...]:
    return (
        content.event_id,
        content.content_type,
        content.language,
        content.prompt_version,
    )


def _content_revision_order(
    content: GeneratedContentAttempt,
) -> tuple[int, datetime, str]:
    return (content.attempt_number, content.created_at, content.id.hex)


def _expired_claim_order(
    content: GeneratedContentAttempt,
) -> tuple[datetime, datetime, str]:
    assert content.claim is not None
    return (content.claim.lease_expires_at, content.created_at, content.id.hex)


def _guard_content_claim(
    content_id: UUID,
    content: GeneratedContentAttempt | None,
    claim_token: UUID,
    expected_version: int,
) -> StateTransitionResult | None:
    guarded = _guard_version(content_id, content, expected_version)
    if guarded is not None:
        return guarded
    assert content is not None
    if (
        content.generation_status is not ContentGenerationStatus.IN_PROGRESS
        or content.claim is None
    ):
        return _transition_result(
            content.id,
            StateTransitionOutcome.INVALID_STATE,
            content.version,
        )
    if content.claim.token != claim_token:
        return _transition_result(
            content.id,
            StateTransitionOutcome.CLAIM_LOST,
            content.version,
        )
    return None


def _guard_version(
    entity_id: UUID,
    content: GeneratedContentAttempt | None,
    expected_version: int,
) -> StateTransitionResult | None:
    if content is None:
        return _transition_result(
            entity_id,
            StateTransitionOutcome.NOT_FOUND,
            None,
        )
    if content.version != expected_version:
        return _transition_result(
            entity_id,
            StateTransitionOutcome.VERSION_CONFLICT,
            content.version,
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


def _normalize_selector(value: str, *, field_name: str) -> str:
    value = value.strip().lower()
    if not value:
        msg = f"{field_name} must not be empty."
        raise ValueError(msg)
    return value


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
