from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domain.identity import (
    canonicalize_utc,
    hash_identity_fields,
    normalize_utc,
    validate_sha256,
)
from app.domain.lifecycle import PublicationStatus
from app.domain.processing import (
    IdempotentCreateStatus,
    ProcessingError,
    WorkClaim,
)
from app.domain.tenancy import LEGACY_TENANT_ID


@dataclass(slots=True, frozen=True, kw_only=True)
class CreatePublication:
    """Database-independent command for a channel-neutral publication."""

    event_id: UUID
    content_id: UUID
    channel: str
    destination_key: str
    tenant_id: UUID = LEGACY_TENANT_ID
    id: UUID = field(default_factory=uuid4)
    scheduled_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        channel = _normalize_channel(self.channel)
        destination_key = _require_text(
            self.destination_key,
            field_name="destination_key",
        )
        scheduled_at = _normalize_optional_utc(
            self.scheduled_at,
            field_name="scheduled_at",
        )
        created_at = normalize_utc(self.created_at, field_name="created_at")
        object.__setattr__(self, "channel", channel)
        object.__setattr__(self, "destination_key", destination_key)
        object.__setattr__(self, "scheduled_at", scheduled_at)
        object.__setattr__(self, "created_at", created_at)

    @property
    def idempotency_key(self) -> str:
        """Return the deterministic publication identity."""
        return build_publication_idempotency_key(
            event_id=self.event_id,
            content_id=self.content_id,
            tenant_id=self.tenant_id,
            channel=self.channel,
            destination_key=self.destination_key,
        )


@dataclass(slots=True, frozen=True, kw_only=True)
class Publication:
    """Immutable channel-independent publication lifecycle snapshot."""

    id: UUID
    event_id: UUID
    content_id: UUID
    channel: str
    destination_key: str
    idempotency_key: str
    status: PublicationStatus
    attempt_count: int
    created_at: datetime
    updated_at: datetime
    tenant_id: UUID = LEGACY_TENANT_ID
    external_message_id: str | None = None
    scheduled_at: datetime | None = None
    next_retry_at: datetime | None = None
    published_at: datetime | None = None
    claim: WorkClaim | None = None
    last_error: ProcessingError | None = None
    version: int = 1

    def __post_init__(self) -> None:
        channel = _normalize_channel(self.channel)
        destination_key = _require_text(
            self.destination_key,
            field_name="destination_key",
        )
        created_at = normalize_utc(self.created_at, field_name="created_at")
        updated_at = normalize_utc(self.updated_at, field_name="updated_at")
        scheduled_at = _normalize_optional_utc(
            self.scheduled_at,
            field_name="scheduled_at",
        )
        next_retry_at = _normalize_optional_utc(
            self.next_retry_at,
            field_name="next_retry_at",
        )
        published_at = _normalize_optional_utc(
            self.published_at,
            field_name="published_at",
        )
        validate_sha256(
            self.idempotency_key,
            field_name="Publication idempotency key",
        )
        expected_key = build_publication_idempotency_key(
            event_id=self.event_id,
            content_id=self.content_id,
            tenant_id=self.tenant_id,
            channel=channel,
            destination_key=destination_key,
        )
        if self.idempotency_key != expected_key:
            msg = "Publication idempotency key does not match its identity inputs."
            raise ValueError(msg)
        if self.attempt_count < 0:
            msg = "Publication attempt count must not be negative."
            raise ValueError(msg)
        if self.version < 1:
            msg = "Publication version must be positive."
            raise ValueError(msg)
        if updated_at < created_at:
            msg = "Publication update time must not predate creation time."
            raise ValueError(msg)
        if published_at is not None and published_at < created_at:
            msg = "Publication time must not predate creation time."
            raise ValueError(msg)
        if self.status is PublicationStatus.IN_PROGRESS:
            if self.claim is None:
                msg = "In-progress publication requires a work claim."
                raise ValueError(msg)
        elif self.claim is not None:
            msg = "A publication claim is valid only while delivery is in progress."
            raise ValueError(msg)
        if self.status is PublicationStatus.PUBLISHED:
            if published_at is None or not _has_text(self.external_message_id):
                msg = "Published delivery requires time and external message ID."
                raise ValueError(msg)
        if self.status in {PublicationStatus.FAILED, PublicationStatus.AMBIGUOUS}:
            if self.last_error is None:
                msg = f"{self.status.value} publication requires error details."
                raise ValueError(msg)

        object.__setattr__(self, "channel", channel)
        object.__setattr__(self, "destination_key", destination_key)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)
        object.__setattr__(self, "scheduled_at", scheduled_at)
        object.__setattr__(self, "next_retry_at", next_retry_at)
        object.__setattr__(self, "published_at", published_at)

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic serialization-safe mapping."""
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "event_id": str(self.event_id),
            "content_id": str(self.content_id),
            "channel": self.channel,
            "destination_key": self.destination_key,
            "idempotency_key": self.idempotency_key,
            "status": self.status.value,
            "attempt_count": self.attempt_count,
            "external_message_id": self.external_message_id,
            "scheduled_at": (
                canonicalize_utc(self.scheduled_at)
                if self.scheduled_at is not None
                else None
            ),
            "next_retry_at": (
                canonicalize_utc(self.next_retry_at)
                if self.next_retry_at is not None
                else None
            ),
            "published_at": (
                canonicalize_utc(self.published_at)
                if self.published_at is not None
                else None
            ),
            "created_at": canonicalize_utc(self.created_at),
            "updated_at": canonicalize_utc(self.updated_at),
            "version": self.version,
        }


@dataclass(slots=True, frozen=True)
class PublicationCreateResult:
    """Result of creating a publication by idempotency key."""

    publication: Publication
    status: IdempotentCreateStatus

    @property
    def created(self) -> bool:
        """Return whether the publication was newly created."""
        return self.status is IdempotentCreateStatus.CREATED


@dataclass(slots=True, frozen=True)
class ClaimedPublication:
    """Publication paired with its active delivery claim."""

    publication: Publication
    claim: WorkClaim


def build_publication_idempotency_key(
    *,
    event_id: UUID,
    content_id: UUID,
    channel: str,
    destination_key: str,
    tenant_id: UUID = LEGACY_TENANT_ID,
) -> str:
    """Build the deterministic identity for one channel delivery."""
    return hash_identity_fields(
        str(tenant_id),
        str(event_id),
        str(content_id),
        _normalize_channel(channel),
        _require_text(destination_key, field_name="destination_key"),
    )


def _normalize_channel(value: str) -> str:
    return _require_text(value, field_name="channel").lower()


def _require_text(value: str, *, field_name: str) -> str:
    if not value.strip():
        msg = f"{field_name} must not be empty."
        raise ValueError(msg)
    return value.strip()


def _has_text(value: str | None) -> bool:
    return value is not None and bool(value.strip())


def _normalize_optional_utc(
    value: datetime | None,
    *,
    field_name: str,
) -> datetime | None:
    return normalize_utc(value, field_name=field_name) if value is not None else None
