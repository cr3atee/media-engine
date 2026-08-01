from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from app.domain.admin_actions import (
    AdminAction,
    AdminActionType,
    AdminResourceType,
    AmbiguousPublicationResolution,
    build_admin_request_fingerprint,
    normalize_optional_reason,
    utc_now,
)
from app.domain.generated_content import GeneratedContentAttempt
from app.domain.lifecycle import (
    ContentGenerationStatus,
    ContentReviewStatus,
    PublicationStatus,
)
from app.domain.processing import StateTransitionOutcome, StateTransitionResult
from app.domain.publications import Publication
from app.repositories.provider import RepositoryProvider
from app.services.repository_scope import RepositoryScopeFactory

type Clock = Callable[[], datetime]
type ActionIdFactory = Callable[[], UUID]

_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


@dataclass(slots=True, frozen=True, kw_only=True)
class AdminCommandContext:
    """Authenticated, correlated context shared by one admin command."""

    actor_id: str
    request_id: str
    idempotency_key: str

    def __post_init__(self) -> None:
        actor_id = _require_bounded_text(
            self.actor_id,
            field_name="actor_id",
            maximum_length=128,
        )
        request_id = _require_bounded_text(
            self.request_id,
            field_name="request_id",
            maximum_length=128,
        )
        idempotency_key = self.idempotency_key.strip()
        if not _IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
            msg = "Idempotency key has an invalid format."
            raise ValueError(msg)
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "idempotency_key", idempotency_key)


@dataclass(slots=True, frozen=True, kw_only=True)
class ContentReviewCommand:
    """Expected-version command for one generated-content review decision."""

    content_id: UUID
    expected_version: int
    reason: str | None = None


@dataclass(slots=True, frozen=True, kw_only=True)
class PublicationCommand:
    """Expected-version command for retrying or cancelling a publication."""

    publication_id: UUID
    expected_version: int
    reason: str


@dataclass(slots=True, frozen=True, kw_only=True)
class ResolvePublicationCommand:
    """Explicit resolution command for one ambiguous publication."""

    publication_id: UUID
    expected_version: int
    resolution: AmbiguousPublicationResolution
    reason: str
    external_message_id: str | None = None


@dataclass(slots=True, frozen=True, kw_only=True)
class AdminMutationResult:
    """Stable ORM-free result of an accepted or replayed admin command."""

    action_id: UUID
    action: AdminActionType
    resource_type: AdminResourceType
    resource_id: UUID
    previous_state: str
    resulting_state: str
    resulting_version: int
    request_id: str
    recorded_at: datetime
    replayed: bool


class AdminCommandError(Exception):
    """Safe application failure with a stable public code and details."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        resource_type: AdminResourceType,
        resource_id: UUID,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.details = {
            "resource_type": resource_type.value,
            "resource_id": str(resource_id),
            **dict(details or {}),
        }
        super().__init__(message)


class AdminMutationService:
    """Execute guarded admin mutations and their audit records atomically."""

    def __init__(
        self,
        repository_scope_factory: RepositoryScopeFactory,
        *,
        maximum_publication_attempts: int,
        clock: Clock = utc_now,
        action_id_factory: ActionIdFactory = uuid4,
    ) -> None:
        if maximum_publication_attempts < 1:
            msg = "Maximum publication attempts must be positive."
            raise ValueError(msg)
        self._repository_scope_factory = repository_scope_factory
        self._maximum_publication_attempts = maximum_publication_attempts
        self._clock = clock
        self._action_id_factory = action_id_factory

    async def approve(
        self,
        command: ContentReviewCommand,
        context: AdminCommandContext,
    ) -> AdminMutationResult:
        """Approve reviewable generated content."""
        return await self._review_content(
            command,
            context,
            action=AdminActionType.APPROVE_CONTENT,
            target=ContentReviewStatus.APPROVED,
            reason_required=False,
        )

    async def reject(
        self,
        command: ContentReviewCommand,
        context: AdminCommandContext,
    ) -> AdminMutationResult:
        """Reject reviewable generated content with an operator reason."""
        return await self._review_content(
            command,
            context,
            action=AdminActionType.REJECT_CONTENT,
            target=ContentReviewStatus.REJECTED,
            reason_required=True,
        )

    async def retry(
        self,
        command: PublicationCommand,
        context: AdminCommandContext,
    ) -> AdminMutationResult:
        """Return one explicitly retryable failed publication to pending."""
        reason = _require_reason(command.reason)
        expected_version = _validate_expected_version(command.expected_version)
        specification = _CommandSpecification(
            action=AdminActionType.RETRY_PUBLICATION,
            resource_type=AdminResourceType.PUBLICATION,
            resource_id=command.publication_id,
            expected_version=expected_version,
            reason=reason,
        )
        async with self._repository_scope_factory() as repositories:
            replay = await self._prepare(repositories, context, specification)
            if replay is not None:
                return replay
            publication = await repositories.publications.get_by_id(
                command.publication_id
            )
            _require_resource(publication, specification)
            assert publication is not None
            _guard_expected_version(publication.version, specification)
            _guard_retryable_publication(
                publication,
                maximum_attempts=self._maximum_publication_attempts,
                specification=specification,
            )
            transition = await repositories.publications.retry_failed(
                publication.id,
                self._clock(),
                expected_version,
            )
            return await self._record_transition(
                repositories,
                context,
                specification,
                previous_state=publication.status.value,
                resulting_state=PublicationStatus.PENDING.value,
                transition=transition,
            )

    async def cancel(
        self,
        command: PublicationCommand,
        context: AdminCommandContext,
    ) -> AdminMutationResult:
        """Cancel pending or explicitly retryable publication work."""
        reason = _require_reason(command.reason)
        expected_version = _validate_expected_version(command.expected_version)
        specification = _CommandSpecification(
            action=AdminActionType.CANCEL_PUBLICATION,
            resource_type=AdminResourceType.PUBLICATION,
            resource_id=command.publication_id,
            expected_version=expected_version,
            reason=reason,
        )
        async with self._repository_scope_factory() as repositories:
            replay = await self._prepare(repositories, context, specification)
            if replay is not None:
                return replay
            publication = await repositories.publications.get_by_id(
                command.publication_id
            )
            _require_resource(publication, specification)
            assert publication is not None
            _guard_expected_version(publication.version, specification)
            _guard_cancellable_publication(publication, specification)
            transition = await repositories.publications.cancel(
                publication.id,
                self._clock(),
                expected_version,
            )
            return await self._record_transition(
                repositories,
                context,
                specification,
                previous_state=publication.status.value,
                resulting_state=PublicationStatus.CANCELLED.value,
                transition=transition,
            )

    async def resolve_ambiguous(
        self,
        command: ResolvePublicationCommand,
        context: AdminCommandContext,
    ) -> AdminMutationResult:
        """Resolve an ambiguous publication without contacting its provider."""
        reason = _require_reason(command.reason)
        expected_version = _validate_expected_version(command.expected_version)
        action, target_status = _resolution_target(command.resolution)
        external_message_id = _normalize_resolution_message_id(
            command.resolution,
            command.external_message_id,
        )
        metadata: tuple[tuple[str, str], ...] = (
            ("resolution", command.resolution.value),
        )
        if external_message_id is not None:
            metadata = metadata + (("external_message_id", external_message_id),)
        specification = _CommandSpecification(
            action=action,
            resource_type=AdminResourceType.PUBLICATION,
            resource_id=command.publication_id,
            expected_version=expected_version,
            reason=reason,
            metadata=metadata,
        )
        async with self._repository_scope_factory() as repositories:
            replay = await self._prepare(repositories, context, specification)
            if replay is not None:
                return replay
            publication = await repositories.publications.get_by_id(
                command.publication_id
            )
            _require_resource(publication, specification)
            assert publication is not None
            _guard_expected_version(publication.version, specification)
            if publication.status is not PublicationStatus.AMBIGUOUS:
                raise _invalid_transition(
                    specification,
                    current_state=publication.status.value,
                    message="Only an ambiguous publication can be resolved.",
                )
            transition = await repositories.publications.resolve_ambiguous(
                publication.id,
                target_status,
                self._clock(),
                expected_version,
                external_message_id,
            )
            return await self._record_transition(
                repositories,
                context,
                specification,
                previous_state=publication.status.value,
                resulting_state=target_status.value,
                transition=transition,
            )

    async def _review_content(
        self,
        command: ContentReviewCommand,
        context: AdminCommandContext,
        *,
        action: AdminActionType,
        target: ContentReviewStatus,
        reason_required: bool,
    ) -> AdminMutationResult:
        reason = normalize_optional_reason(command.reason)
        if reason_required and reason is None:
            raise ValueError("A rejection reason is required.")
        expected_version = _validate_expected_version(command.expected_version)
        specification = _CommandSpecification(
            action=action,
            resource_type=AdminResourceType.CONTENT,
            resource_id=command.content_id,
            expected_version=expected_version,
            reason=reason,
        )
        async with self._repository_scope_factory() as repositories:
            replay = await self._prepare(repositories, context, specification)
            if replay is not None:
                return replay
            content = await repositories.generated_contents.get_by_id(
                command.content_id
            )
            _require_resource(content, specification)
            assert content is not None
            _guard_expected_version(content.version, specification)
            _guard_reviewable_content(content, specification)
            transition = await repositories.generated_contents.set_review_status(
                content.id,
                target,
                self._clock(),
                expected_version,
            )
            return await self._record_transition(
                repositories,
                context,
                specification,
                previous_state=content.review_status.value,
                resulting_state=target.value,
                transition=transition,
            )

    async def _prepare(
        self,
        repositories: RepositoryProvider,
        context: AdminCommandContext,
        specification: _CommandSpecification,
    ) -> AdminMutationResult | None:
        await repositories.admin_actions.acquire_idempotency_lock(
            context.idempotency_key
        )
        existing = await repositories.admin_actions.get_by_idempotency_key(
            context.idempotency_key
        )
        if existing is None:
            return None
        fingerprint = _fingerprint(context, specification)
        if existing.request_fingerprint != fingerprint:
            raise AdminCommandError(
                "idempotency_conflict",
                "Idempotency key is already bound to another command.",
                resource_type=specification.resource_type,
                resource_id=specification.resource_id,
            )
        return _result(existing, replayed=True)

    async def _record_transition(
        self,
        repositories: RepositoryProvider,
        context: AdminCommandContext,
        specification: _CommandSpecification,
        *,
        previous_state: str,
        resulting_state: str,
        transition: StateTransitionResult,
    ) -> AdminMutationResult:
        _raise_for_transition(transition, specification, previous_state)
        assert transition.version is not None
        action = AdminAction(
            id=self._action_id_factory(),
            action=specification.action,
            resource_type=specification.resource_type,
            resource_id=specification.resource_id,
            previous_state=previous_state,
            resulting_state=resulting_state,
            reason=specification.reason,
            actor_id=context.actor_id,
            request_id=context.request_id,
            idempotency_key=context.idempotency_key,
            request_fingerprint=_fingerprint(context, specification),
            expected_version=specification.expected_version,
            resulting_version=transition.version,
            created_at=self._clock(),
            metadata=specification.metadata,
        )
        stored = await repositories.admin_actions.append(action)
        return _result(stored, replayed=False)


@dataclass(slots=True, frozen=True, kw_only=True)
class _CommandSpecification:
    action: AdminActionType
    resource_type: AdminResourceType
    resource_id: UUID
    expected_version: int
    reason: str | None
    metadata: tuple[tuple[str, str], ...] = ()


def _fingerprint(
    context: AdminCommandContext,
    specification: _CommandSpecification,
) -> str:
    return build_admin_request_fingerprint(
        actor_id=context.actor_id,
        action=specification.action,
        resource_type=specification.resource_type,
        resource_id=specification.resource_id,
        expected_version=specification.expected_version,
        reason=specification.reason,
        metadata=specification.metadata,
    )


def _result(action: AdminAction, *, replayed: bool) -> AdminMutationResult:
    return AdminMutationResult(
        action_id=action.id,
        action=action.action,
        resource_type=action.resource_type,
        resource_id=action.resource_id,
        previous_state=action.previous_state,
        resulting_state=action.resulting_state,
        resulting_version=action.resulting_version,
        request_id=action.request_id,
        recorded_at=action.created_at,
        replayed=replayed,
    )


def _guard_reviewable_content(
    content: GeneratedContentAttempt,
    specification: _CommandSpecification,
) -> None:
    if (
        content.generation_status is not ContentGenerationStatus.GENERATED
        or content.review_status is not ContentReviewStatus.PENDING
    ):
        raise _invalid_transition(
            specification,
            current_state=content.review_status.value,
            message="Only generated content pending review can be decided.",
        )


def _guard_retryable_publication(
    publication: Publication,
    *,
    maximum_attempts: int,
    specification: _CommandSpecification,
) -> None:
    if (
        publication.status is not PublicationStatus.FAILED
        or publication.next_retry_at is None
    ):
        raise _invalid_transition(
            specification,
            current_state=publication.status.value,
            message="Publication is not in a known retryable failed state.",
        )
    if publication.attempt_count >= maximum_attempts:
        raise _invalid_transition(
            specification,
            current_state=publication.status.value,
            message="Publication retry attempt budget is exhausted.",
        )


def _guard_cancellable_publication(
    publication: Publication,
    specification: _CommandSpecification,
) -> None:
    pending = publication.status is PublicationStatus.PENDING
    retryable_failure = (
        publication.status is PublicationStatus.FAILED
        and publication.next_retry_at is not None
    )
    if not pending and not retryable_failure:
        raise _invalid_transition(
            specification,
            current_state=publication.status.value,
            message=(
                "Only pending or retryable failed publication work can be cancelled."
            ),
        )


def _guard_expected_version(
    current_version: int,
    specification: _CommandSpecification,
) -> None:
    if current_version != specification.expected_version:
        raise AdminCommandError(
            "optimistic_concurrency_conflict",
            "Resource version does not match the expected version.",
            resource_type=specification.resource_type,
            resource_id=specification.resource_id,
            details={"current_version": current_version},
        )


def _require_resource(
    resource: object | None,
    specification: _CommandSpecification,
) -> None:
    if resource is None:
        raise AdminCommandError(
            "resource_not_found",
            "Administrative target was not found.",
            resource_type=specification.resource_type,
            resource_id=specification.resource_id,
        )


def _raise_for_transition(
    transition: StateTransitionResult,
    specification: _CommandSpecification,
    previous_state: str,
) -> None:
    if transition.outcome is StateTransitionOutcome.APPLIED:
        return
    if transition.outcome is StateTransitionOutcome.NOT_FOUND:
        raise AdminCommandError(
            "resource_not_found",
            "Administrative target was not found.",
            resource_type=specification.resource_type,
            resource_id=specification.resource_id,
        )
    if transition.outcome is StateTransitionOutcome.VERSION_CONFLICT:
        raise AdminCommandError(
            "optimistic_concurrency_conflict",
            "Resource version does not match the expected version.",
            resource_type=specification.resource_type,
            resource_id=specification.resource_id,
            details={"current_version": transition.version},
        )
    raise _invalid_transition(
        specification,
        current_state=previous_state,
        message="Requested lifecycle transition is not allowed.",
    )


def _invalid_transition(
    specification: _CommandSpecification,
    *,
    current_state: str,
    message: str,
) -> AdminCommandError:
    return AdminCommandError(
        "invalid_transition",
        message,
        resource_type=specification.resource_type,
        resource_id=specification.resource_id,
        details={"current_state": current_state},
    )


def _resolution_target(
    resolution: AmbiguousPublicationResolution,
) -> tuple[AdminActionType, PublicationStatus]:
    if resolution is AmbiguousPublicationResolution.DELIVERED:
        return (
            AdminActionType.RESOLVE_PUBLICATION_DELIVERED,
            PublicationStatus.PUBLISHED,
        )
    if resolution is AmbiguousPublicationResolution.NOT_DELIVERED:
        return (
            AdminActionType.RESOLVE_PUBLICATION_NOT_DELIVERED,
            PublicationStatus.PENDING,
        )
    return (
        AdminActionType.RESOLVE_PUBLICATION_CANCELLED,
        PublicationStatus.CANCELLED,
    )


def _normalize_resolution_message_id(
    resolution: AmbiguousPublicationResolution,
    external_message_id: str | None,
) -> str | None:
    if resolution is AmbiguousPublicationResolution.DELIVERED:
        if external_message_id is None:
            raise ValueError("Delivered resolution requires an external message ID.")
        return _require_bounded_text(
            external_message_id,
            field_name="external_message_id",
            maximum_length=255,
        )
    if external_message_id is not None:
        raise ValueError("External message ID is valid only for delivered resolution.")
    return None


def _validate_expected_version(expected_version: int) -> int:
    if expected_version < 1:
        msg = "Expected version must be positive."
        raise ValueError(msg)
    return expected_version


def _require_reason(reason: str) -> str:
    normalized = normalize_optional_reason(reason)
    if normalized is None:
        msg = "An administrative reason is required."
        raise ValueError(msg)
    return normalized


def _require_bounded_text(
    value: str,
    *,
    field_name: str,
    maximum_length: int,
) -> str:
    normalized = value.strip()
    if not normalized:
        msg = f"{field_name} must not be empty."
        raise ValueError(msg)
    if len(normalized) > maximum_length:
        msg = f"{field_name} must not exceed {maximum_length} characters."
        raise ValueError(msg)
    return normalized
