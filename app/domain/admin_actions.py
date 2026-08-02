from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from uuid import UUID

from app.domain.identity import normalize_utc, validate_sha256
from app.domain.tenancy import LEGACY_TENANT_ID


class AdminActionType(StrEnum):
    """Stable names for accepted administrative mutations."""

    APPROVE_CONTENT = "approve_content"
    REJECT_CONTENT = "reject_content"
    RETRY_PUBLICATION = "retry_publication"
    CANCEL_PUBLICATION = "cancel_publication"
    RESOLVE_PUBLICATION_DELIVERED = "resolve_publication_delivered"
    RESOLVE_PUBLICATION_NOT_DELIVERED = "resolve_publication_not_delivered"
    RESOLVE_PUBLICATION_CANCELLED = "resolve_publication_cancelled"


class AdminResourceType(StrEnum):
    """Resource kinds supported by guarded administration commands."""

    CONTENT = "content"
    PUBLICATION = "publication"


class AdminActorType(StrEnum):
    """Actor categories represented by immutable audit records."""

    API_KEY = "api_key"
    PLATFORM_ADMIN = "platform_admin"
    USER = "user"
    SYSTEM = "system"
    WORKER = "worker"
    MIGRATION = "migration"


class AmbiguousPublicationResolution(StrEnum):
    """Explicit operator decisions for an ambiguous publication outcome."""

    DELIVERED = "delivered"
    NOT_DELIVERED = "not_delivered"
    CANCELLED = "cancelled"


@dataclass(slots=True, frozen=True, kw_only=True)
class AdminAction:
    """Immutable audit record committed with one accepted admin mutation."""

    id: UUID
    action: AdminActionType
    resource_type: AdminResourceType
    resource_id: UUID
    tenant_id: UUID = LEGACY_TENANT_ID
    previous_state: str
    resulting_state: str
    actor_id: str
    actor_type: AdminActorType = AdminActorType.API_KEY
    elevated: bool = False
    request_id: str
    idempotency_key: str
    request_fingerprint: str
    expected_version: int
    resulting_version: int
    created_at: datetime
    reason: str | None = None
    metadata: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        previous_state = _require_text(
            self.previous_state,
            field_name="previous_state",
            maximum_length=64,
        )
        resulting_state = _require_text(
            self.resulting_state,
            field_name="resulting_state",
            maximum_length=64,
        )
        actor_id = _require_text(
            self.actor_id,
            field_name="actor_id",
            maximum_length=128,
        )
        request_id = _require_text(
            self.request_id,
            field_name="request_id",
            maximum_length=128,
        )
        idempotency_key = _require_text(
            self.idempotency_key,
            field_name="idempotency_key",
            maximum_length=128,
        )
        reason = normalize_optional_reason(self.reason)
        created_at = normalize_utc(self.created_at, field_name="created_at")
        validate_sha256(
            self.request_fingerprint,
            field_name="Admin action request fingerprint",
        )
        if self.expected_version < 1:
            msg = "Expected resource version must be positive."
            raise ValueError(msg)
        if self.resulting_version <= self.expected_version:
            msg = "Resulting resource version must exceed the expected version."
            raise ValueError(msg)
        metadata = tuple(sorted(_normalize_metadata(self.metadata)))
        object.__setattr__(self, "previous_state", previous_state)
        object.__setattr__(self, "resulting_state", resulting_state)
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "idempotency_key", idempotency_key)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "metadata", metadata)


def build_admin_request_fingerprint(
    *,
    actor_id: str,
    action: AdminActionType,
    resource_type: AdminResourceType,
    resource_id: UUID,
    expected_version: int,
    reason: str | None,
    metadata: tuple[tuple[str, str], ...] = (),
) -> str:
    """Hash the normalized semantics bound to an idempotency key."""
    normalized_metadata = dict(sorted(_normalize_metadata(metadata)))
    payload = {
        "action": action.value,
        "actor_id": _require_text(
            actor_id,
            field_name="actor_id",
            maximum_length=128,
        ),
        "expected_version": expected_version,
            "metadata": normalized_metadata,
            "reason": normalize_optional_reason(reason),
            "resource_id": str(resource_id),
            "resource_type": resource_type.value,
        }
    serialized = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


def normalize_optional_reason(reason: str | None) -> str | None:
    """Normalize a bounded human reason without retaining arbitrary payloads."""
    if reason is None:
        return None
    normalized = " ".join(reason.split())
    if not normalized:
        return None
    if len(normalized) > 2000:
        msg = "Administrative reason must not exceed 2000 characters."
        raise ValueError(msg)
    return normalized


def utc_now() -> datetime:
    """Return an aware UTC timestamp for admin command defaults."""
    return datetime.now(UTC)


def _normalize_metadata(
    metadata: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    normalized: list[tuple[str, str]] = []
    seen: set[str] = set()
    for key, value in metadata:
        clean_key = _require_text(key, field_name="metadata key", maximum_length=64)
        clean_value = _require_text(
            value,
            field_name=f"metadata[{clean_key}]",
            maximum_length=255,
        )
        if clean_key in seen:
            msg = f"Administrative metadata key is duplicated: {clean_key}."
            raise ValueError(msg)
        seen.add(clean_key)
        normalized.append((clean_key, clean_value))
    return tuple(normalized)


def _require_text(value: str, *, field_name: str, maximum_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        msg = f"{field_name} must not be empty."
        raise ValueError(msg)
    if len(normalized) > maximum_length:
        msg = f"{field_name} must not exceed {maximum_length} characters."
        raise ValueError(msg)
    return normalized
