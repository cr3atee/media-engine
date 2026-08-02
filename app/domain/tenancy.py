from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from app.domain.identity import normalize_utc

LEGACY_TENANT_ID = UUID("00000000-0000-4000-8000-000000000001")
LEGACY_TENANT_SLUG = "legacy"
LEGACY_TENANT_NAME = "Legacy Tenant"

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
_RESERVED_SLUGS = frozenset({"admin", "api", "legacy", "me", "platform", "system"})


class TenantRole(StrEnum):
    """Canonical tenant roles used for membership authorization."""

    OWNER = "owner"
    ADMINISTRATOR = "administrator"
    REVIEWER = "reviewer"
    OPERATOR = "operator"
    VIEWER = "viewer"


@dataclass(slots=True, frozen=True, kw_only=True)
class User:
    """Durable human identity without authentication credentials."""

    id: UUID
    email: str
    display_name: str | None = None
    enabled: bool = True
    created_at: datetime
    updated_at: datetime
    version: int = 1

    def __post_init__(self) -> None:
        email = normalize_email(self.email)
        display_name = _normalize_optional_text(
            self.display_name,
            field_name="display_name",
            maximum_length=255,
        )
        created_at = normalize_utc(self.created_at, field_name="created_at")
        updated_at = normalize_utc(self.updated_at, field_name="updated_at")
        _validate_version(self.version, field_name="User version")
        if updated_at < created_at:
            msg = "User update time must not predate creation time."
            raise ValueError(msg)
        object.__setattr__(self, "email", email)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)


@dataclass(slots=True, frozen=True, kw_only=True)
class Tenant:
    """Durable tenant/workspace identity that owns seller data."""

    id: UUID
    name: str
    slug: str
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
    version: int = 1

    def __post_init__(self) -> None:
        name = _require_text(self.name, field_name="tenant name", maximum_length=255)
        slug = normalize_tenant_slug(self.slug, allow_legacy=self.id == LEGACY_TENANT_ID)
        created_at = normalize_utc(self.created_at, field_name="created_at")
        updated_at = normalize_utc(self.updated_at, field_name="updated_at")
        _validate_version(self.version, field_name="Tenant version")
        if updated_at < created_at:
            msg = "Tenant update time must not predate creation time."
            raise ValueError(msg)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "slug", slug)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)


@dataclass(slots=True, frozen=True, kw_only=True)
class Membership:
    """Durable relationship between one user and one tenant role."""

    id: UUID
    user_id: UUID
    tenant_id: UUID
    role: TenantRole
    is_active: bool = True
    joined_at: datetime
    updated_at: datetime
    version: int = 1

    def __post_init__(self) -> None:
        joined_at = normalize_utc(self.joined_at, field_name="joined_at")
        updated_at = normalize_utc(self.updated_at, field_name="updated_at")
        _validate_version(self.version, field_name="Membership version")
        if updated_at < joined_at:
            msg = "Membership update time must not predate join time."
            raise ValueError(msg)
        object.__setattr__(self, "joined_at", joined_at)
        object.__setattr__(self, "updated_at", updated_at)


def normalize_email(value: str) -> str:
    """Normalize the MVP email identity without claiming RFC completeness."""
    normalized = value.strip().lower()
    if not normalized or len(normalized) > 320 or not _EMAIL_PATTERN.fullmatch(
        normalized
    ):
        msg = "Email must be a non-empty normalized address."
        raise ValueError(msg)
    return normalized


def normalize_tenant_slug(value: str, *, allow_legacy: bool = False) -> str:
    """Normalize and validate a stable tenant slug."""
    normalized = value.strip().lower()
    if not _SLUG_PATTERN.fullmatch(normalized):
        msg = "Tenant slug must be 3-64 lowercase letters, numbers, or hyphens."
        raise ValueError(msg)
    if normalized in _RESERVED_SLUGS and not (allow_legacy and normalized == "legacy"):
        msg = f"Tenant slug is reserved: {normalized}."
        raise ValueError(msg)
    return normalized


def utc_now() -> datetime:
    """Return an aware UTC timestamp for identity defaults."""
    return datetime.now(UTC)


def _require_text(value: str, *, field_name: str, maximum_length: int) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        msg = f"{field_name} must not be empty."
        raise ValueError(msg)
    if len(normalized) > maximum_length:
        msg = f"{field_name} must not exceed {maximum_length} characters."
        raise ValueError(msg)
    return normalized


def _normalize_optional_text(
    value: str | None,
    *,
    field_name: str,
    maximum_length: int,
) -> str | None:
    if value is None:
        return None
    return _require_text(value, field_name=field_name, maximum_length=maximum_length)


def _validate_version(value: int, *, field_name: str) -> None:
    if value < 1:
        msg = f"{field_name} must be positive."
        raise ValueError(msg)

