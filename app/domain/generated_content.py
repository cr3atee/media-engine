from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from uuid import UUID, uuid4

from app.domain.identity import (
    canonicalize_utc,
    hash_identity_fields,
    normalize_utc,
    validate_sha256,
)
from app.domain.lifecycle import ContentGenerationStatus, ContentReviewStatus
from app.domain.processing import (
    IdempotentCreateStatus,
    ProcessingError,
    WorkClaim,
)
from app.domain.tenancy import LEGACY_TENANT_ID


class ContentOrigin(StrEnum):
    """Origin of an immutable content revision."""

    AI = "ai"
    HUMAN_EDIT = "human_edit"


@dataclass(slots=True, frozen=True, kw_only=True)
class CreateContentAttempt:
    """Database-independent command for a new content attempt."""

    event_id: UUID
    content_type: str
    language: str
    prompt_version: str
    attempt_number: int
    tenant_id: UUID = LEGACY_TENANT_ID
    id: UUID = field(default_factory=uuid4)
    parent_content_id: UUID | None = None
    origin: ContentOrigin = ContentOrigin.AI
    provider: str | None = None
    model: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        content_type = _normalize_code(self.content_type, field_name="content_type")
        language = _normalize_code(self.language, field_name="language")
        prompt_version = _require_text(
            self.prompt_version,
            field_name="prompt_version",
        )
        created_at = normalize_utc(self.created_at, field_name="created_at")
        _validate_attempt_number(self.attempt_number)
        _validate_optional_label(self.provider, field_name="provider")
        _validate_optional_label(self.model, field_name="model")
        if self.origin is ContentOrigin.HUMAN_EDIT:
            if self.parent_content_id is None:
                msg = "Human-edited content requires a parent revision."
                raise ValueError(msg)
            if self.provider is not None or self.model is not None:
                msg = "Human-edited content cannot declare an AI provider or model."
                raise ValueError(msg)
        object.__setattr__(self, "content_type", content_type)
        object.__setattr__(self, "language", language)
        object.__setattr__(self, "prompt_version", prompt_version)
        object.__setattr__(self, "created_at", created_at)

    @property
    def idempotency_key(self) -> str:
        """Return the deterministic identity of this generation attempt."""
        return build_content_idempotency_key(
            event_id=self.event_id,
            tenant_id=self.tenant_id,
            content_type=self.content_type,
            language=self.language,
            prompt_version=self.prompt_version,
            attempt_number=self.attempt_number,
        )


@dataclass(slots=True, frozen=True, kw_only=True)
class GeneratedContentAttempt:
    """Immutable snapshot of one content-generation attempt or revision."""

    id: UUID
    event_id: UUID
    content_type: str
    language: str
    origin: ContentOrigin
    prompt_version: str
    generation_status: ContentGenerationStatus
    review_status: ContentReviewStatus
    attempt_number: int
    idempotency_key: str
    created_at: datetime
    updated_at: datetime
    tenant_id: UUID = LEGACY_TENANT_ID
    parent_content_id: UUID | None = None
    provider: str | None = None
    model: str | None = None
    content_text: str | None = None
    content_checksum: str | None = None
    next_retry_at: datetime | None = None
    claim: WorkClaim | None = None
    last_error: ProcessingError | None = None
    completed_at: datetime | None = None
    version: int = 1

    def __post_init__(self) -> None:
        content_type = _normalize_code(self.content_type, field_name="content_type")
        language = _normalize_code(self.language, field_name="language")
        prompt_version = _require_text(
            self.prompt_version,
            field_name="prompt_version",
        )
        created_at = normalize_utc(self.created_at, field_name="created_at")
        updated_at = normalize_utc(self.updated_at, field_name="updated_at")
        completed_at = _normalize_optional_utc(
            self.completed_at,
            field_name="completed_at",
        )
        next_retry_at = _normalize_optional_utc(
            self.next_retry_at,
            field_name="next_retry_at",
        )
        _validate_attempt_number(self.attempt_number)
        _validate_optional_label(self.provider, field_name="provider")
        _validate_optional_label(self.model, field_name="model")
        validate_sha256(self.idempotency_key, field_name="Content idempotency key")

        expected_key = build_content_idempotency_key(
            event_id=self.event_id,
            tenant_id=self.tenant_id,
            content_type=content_type,
            language=language,
            prompt_version=prompt_version,
            attempt_number=self.attempt_number,
        )
        if self.idempotency_key != expected_key:
            msg = "Content idempotency key does not match its identity inputs."
            raise ValueError(msg)
        if updated_at < created_at:
            msg = "Content update time must not predate creation time."
            raise ValueError(msg)
        if completed_at is not None and completed_at < created_at:
            msg = "Content completion time must not predate creation time."
            raise ValueError(msg)
        if self.version < 1:
            msg = "Content version must be positive."
            raise ValueError(msg)
        if self.generation_status is ContentGenerationStatus.IN_PROGRESS:
            if self.claim is None:
                msg = "In-progress content generation requires a work claim."
                raise ValueError(msg)
        elif self.claim is not None:
            msg = "A content claim is valid only while generation is in progress."
            raise ValueError(msg)

        if self.generation_status is ContentGenerationStatus.GENERATED:
            _validate_generated_content(
                self.content_text,
                self.content_checksum,
                completed_at,
            )
        elif self.content_checksum is not None:
            msg = "Content checksum is valid only for generated content."
            raise ValueError(msg)

        if self.generation_status is ContentGenerationStatus.FAILED:
            if self.last_error is None:
                msg = "Failed content generation requires error details."
                raise ValueError(msg)
        if self.origin is ContentOrigin.HUMAN_EDIT:
            if self.parent_content_id is None:
                msg = "Human-edited content requires a parent revision."
                raise ValueError(msg)
            if self.provider is not None or self.model is not None:
                msg = "Human-edited content cannot declare an AI provider or model."
                raise ValueError(msg)
            if self.generation_status is not ContentGenerationStatus.GENERATED:
                msg = "A human-edited revision must contain completed content."
                raise ValueError(msg)

        object.__setattr__(self, "content_type", content_type)
        object.__setattr__(self, "language", language)
        object.__setattr__(self, "prompt_version", prompt_version)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)
        object.__setattr__(self, "completed_at", completed_at)
        object.__setattr__(self, "next_retry_at", next_retry_at)

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic serialization-safe mapping."""
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "event_id": str(self.event_id),
            "parent_content_id": (
                str(self.parent_content_id)
                if self.parent_content_id is not None
                else None
            ),
            "content_type": self.content_type,
            "language": self.language,
            "origin": self.origin.value,
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "content_text": self.content_text,
            "generation_status": self.generation_status.value,
            "review_status": self.review_status.value,
            "attempt_number": self.attempt_number,
            "idempotency_key": self.idempotency_key,
            "content_checksum": self.content_checksum,
            "created_at": canonicalize_utc(self.created_at),
            "updated_at": canonicalize_utc(self.updated_at),
            "completed_at": (
                canonicalize_utc(self.completed_at)
                if self.completed_at is not None
                else None
            ),
            "version": self.version,
        }


@dataclass(slots=True, frozen=True)
class ContentCreateResult:
    """Result of creating a content attempt by idempotency key."""

    content: GeneratedContentAttempt
    status: IdempotentCreateStatus

    @property
    def created(self) -> bool:
        """Return whether the content attempt was newly created."""
        return self.status is IdempotentCreateStatus.CREATED


@dataclass(slots=True, frozen=True)
class ClaimedContentAttempt:
    """Content attempt paired with its active work claim."""

    content: GeneratedContentAttempt
    claim: WorkClaim


def build_content_idempotency_key(
    *,
    event_id: UUID,
    content_type: str,
    language: str,
    prompt_version: str,
    attempt_number: int,
    tenant_id: UUID = LEGACY_TENANT_ID,
) -> str:
    """Build the deterministic identity of a content attempt."""
    _validate_attempt_number(attempt_number)
    return hash_identity_fields(
        str(tenant_id),
        str(event_id),
        _normalize_code(content_type, field_name="content_type"),
        _normalize_code(language, field_name="language"),
        _require_text(prompt_version, field_name="prompt_version"),
        str(attempt_number),
    )


def calculate_content_checksum(content_text: str) -> str:
    """Return the SHA-256 checksum of final UTF-8 content text."""
    if not content_text.strip():
        msg = "Generated content text must not be empty."
        raise ValueError(msg)
    return sha256(content_text.encode("utf-8")).hexdigest()


def _validate_generated_content(
    content_text: str | None,
    content_checksum: str | None,
    completed_at: datetime | None,
) -> None:
    if content_text is None or not content_text.strip():
        msg = "Generated content requires non-empty text."
        raise ValueError(msg)
    if content_checksum is None:
        msg = "Generated content requires a checksum."
        raise ValueError(msg)
    validate_sha256(content_checksum, field_name="Content checksum")
    if content_checksum != calculate_content_checksum(content_text):
        msg = "Content checksum does not match content text."
        raise ValueError(msg)
    if completed_at is None:
        msg = "Generated content requires a completion timestamp."
        raise ValueError(msg)


def _validate_attempt_number(value: int) -> None:
    if value < 1:
        msg = "Content attempt number must be positive."
        raise ValueError(msg)


def _normalize_code(value: str, *, field_name: str) -> str:
    return _require_text(value, field_name=field_name).lower()


def _require_text(value: str, *, field_name: str) -> str:
    if not value.strip():
        msg = f"{field_name} must not be empty."
        raise ValueError(msg)
    return value.strip()


def _validate_optional_label(value: str | None, *, field_name: str) -> None:
    if value is not None and not value.strip():
        msg = f"{field_name} must be non-empty when provided."
        raise ValueError(msg)


def _normalize_optional_utc(
    value: datetime | None,
    *,
    field_name: str,
) -> datetime | None:
    return normalize_utc(value, field_name=field_name) if value is not None else None
