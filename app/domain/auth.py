from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.identity import normalize_utc
from app.domain.tenancy import Membership, Tenant, TenantRole, User


class ActorType(StrEnum):
    """Authenticated actor categories used by seller and internal boundaries."""

    USER = "user"
    API_KEY = "api_key"
    SYSTEM = "system"
    WORKER = "worker"
    PLATFORM_ADMIN = "platform_admin"


class Permission(StrEnum):
    """Stable tenant permissions checked by application services and routes."""

    EVENTS_READ = "events_read"
    CONTENT_READ = "content_read"
    PUBLICATIONS_READ = "publications_read"
    DASHBOARD_READ = "dashboard_read"
    CONTENT_REVIEW = "content_review"
    PUBLICATION_OPERATE = "publication_operate"
    AUDIT_READ = "audit_read"
    INTEGRATION_MANAGE = "integration_manage"
    DESTINATION_MANAGE = "destination_manage"
    MEMBERSHIP_MANAGE = "membership_manage"
    TENANT_SETTINGS_MANAGE = "tenant_settings_manage"
    TENANT_DEACTIVATE = "tenant_deactivate"


@dataclass(slots=True, frozen=True, kw_only=True)
class AuthenticatedPrincipal:
    """Caller identity resolved from a signed access token."""

    actor_type: ActorType
    user_id: UUID
    session_id: UUID
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        issued_at = normalize_utc(self.issued_at, field_name="issued_at")
        expires_at = normalize_utc(self.expires_at, field_name="expires_at")
        if expires_at <= issued_at:
            msg = "Principal expiry must be after issue time."
            raise ValueError(msg)
        object.__setattr__(self, "issued_at", issued_at)
        object.__setattr__(self, "expires_at", expires_at)


@dataclass(slots=True, frozen=True, kw_only=True)
class TenantContext:
    """Authorized tenant context selected for one request or command."""

    principal: AuthenticatedPrincipal
    user: User
    tenant: Tenant
    membership: Membership


@dataclass(slots=True, frozen=True, kw_only=True)
class PasswordCredential:
    """Stored password verifier for one user; never expose via API responses."""

    user_id: UUID
    password_hash: str
    created_at: datetime
    updated_at: datetime
    version: int = 1

    def __post_init__(self) -> None:
        password_hash = self.password_hash.strip()
        if not password_hash:
            msg = "Password hash must not be empty."
            raise ValueError(msg)
        created_at = normalize_utc(self.created_at, field_name="created_at")
        updated_at = normalize_utc(self.updated_at, field_name="updated_at")
        if updated_at < created_at:
            msg = "Password credential update time must not predate creation time."
            raise ValueError(msg)
        if self.version < 1:
            msg = "Password credential version must be positive."
            raise ValueError(msg)
        object.__setattr__(self, "password_hash", password_hash)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)


@dataclass(slots=True, frozen=True, kw_only=True)
class AuthSession:
    """Durable refresh-token session backing short-lived access tokens."""

    id: UUID
    user_id: UUID
    refresh_token_hash: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None
    version: int = 1

    def __post_init__(self) -> None:
        refresh_token_hash = self.refresh_token_hash.strip()
        if not refresh_token_hash:
            msg = "Refresh token hash must not be empty."
            raise ValueError(msg)
        created_at = normalize_utc(self.created_at, field_name="created_at")
        expires_at = normalize_utc(self.expires_at, field_name="expires_at")
        revoked_at = (
            normalize_utc(self.revoked_at, field_name="revoked_at")
            if self.revoked_at is not None
            else None
        )
        last_used_at = (
            normalize_utc(self.last_used_at, field_name="last_used_at")
            if self.last_used_at is not None
            else None
        )
        if expires_at <= created_at:
            msg = "Session expiry must be after creation time."
            raise ValueError(msg)
        if revoked_at is not None and revoked_at < created_at:
            msg = "Session revocation time must not predate creation time."
            raise ValueError(msg)
        if last_used_at is not None and last_used_at < created_at:
            msg = "Session last-use time must not predate creation time."
            raise ValueError(msg)
        if self.version < 1:
            msg = "Session version must be positive."
            raise ValueError(msg)
        object.__setattr__(self, "refresh_token_hash", refresh_token_hash)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(self, "revoked_at", revoked_at)
        object.__setattr__(self, "last_used_at", last_used_at)

    def is_active(self, now: datetime) -> bool:
        """Return whether the session can still authenticate a caller."""
        current_time = normalize_utc(now, field_name="now")
        return self.revoked_at is None and self.expires_at > current_time


@dataclass(slots=True, frozen=True, kw_only=True)
class PasswordResetToken:
    """Durable one-use password reset token hash."""

    id: UUID
    user_id: UUID
    token_hash: str
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None = None
    version: int = 1

    def __post_init__(self) -> None:
        token_hash = self.token_hash.strip()
        if not token_hash:
            msg = "Reset token hash must not be empty."
            raise ValueError(msg)
        created_at = normalize_utc(self.created_at, field_name="created_at")
        expires_at = normalize_utc(self.expires_at, field_name="expires_at")
        used_at = (
            normalize_utc(self.used_at, field_name="used_at")
            if self.used_at is not None
            else None
        )
        if expires_at <= created_at:
            msg = "Reset token expiry must be after creation time."
            raise ValueError(msg)
        if used_at is not None and used_at < created_at:
            msg = "Reset token use time must not predate creation time."
            raise ValueError(msg)
        if self.version < 1:
            msg = "Reset token version must be positive."
            raise ValueError(msg)
        object.__setattr__(self, "token_hash", token_hash)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(self, "used_at", used_at)

    def is_usable(self, now: datetime) -> bool:
        """Return whether the reset token can still be consumed."""
        current_time = normalize_utc(now, field_name="now")
        return self.used_at is None and self.expires_at > current_time


ROLE_PERMISSIONS: dict[TenantRole, frozenset[Permission]] = {
    TenantRole.OWNER: frozenset(Permission),
    TenantRole.ADMINISTRATOR: frozenset(
        {
            Permission.EVENTS_READ,
            Permission.CONTENT_READ,
            Permission.PUBLICATIONS_READ,
            Permission.DASHBOARD_READ,
            Permission.CONTENT_REVIEW,
            Permission.PUBLICATION_OPERATE,
            Permission.AUDIT_READ,
            Permission.INTEGRATION_MANAGE,
            Permission.DESTINATION_MANAGE,
            Permission.TENANT_SETTINGS_MANAGE,
        }
    ),
    TenantRole.REVIEWER: frozenset(
        {
            Permission.EVENTS_READ,
            Permission.CONTENT_READ,
            Permission.PUBLICATIONS_READ,
            Permission.DASHBOARD_READ,
            Permission.CONTENT_REVIEW,
        }
    ),
    TenantRole.OPERATOR: frozenset(
        {
            Permission.EVENTS_READ,
            Permission.CONTENT_READ,
            Permission.PUBLICATIONS_READ,
            Permission.DASHBOARD_READ,
            Permission.PUBLICATION_OPERATE,
        }
    ),
    TenantRole.VIEWER: frozenset(
        {
            Permission.EVENTS_READ,
            Permission.CONTENT_READ,
            Permission.PUBLICATIONS_READ,
            Permission.DASHBOARD_READ,
        }
    ),
}
