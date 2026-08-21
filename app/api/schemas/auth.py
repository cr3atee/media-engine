from __future__ import annotations

from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel


class LoginRequest(ApiModel):
    """Seller login request."""

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=4096)


class RefreshTokenRequest(ApiModel):
    """Refresh-token rotation request."""

    refresh_token: str = Field(min_length=16, max_length=512)


class LogoutRequest(ApiModel):
    """Logout request using the current refresh token."""

    refresh_token: str = Field(min_length=16, max_length=512)


class PasswordResetRequest(ApiModel):
    """Password reset request that does not reveal whether an email exists."""

    email: str = Field(min_length=3, max_length=320)


class PasswordResetCompleteRequest(ApiModel):
    """Password reset completion request."""

    reset_token: str = Field(min_length=16, max_length=512)
    new_password: str = Field(min_length=12, max_length=4096)


class TokenResponse(ApiModel):
    """Access and refresh tokens for a seller session."""

    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int = Field(gt=0)


class AcceptedResponse(ApiModel):
    """Generic accepted response for safe auth operations."""

    status: str


class UserResponse(ApiModel):
    """Authenticated seller user details."""

    id: UUID
    email: str
    display_name: str | None
    enabled: bool


class TenantMembershipResponse(ApiModel):
    """Tenant membership visible to the authenticated seller."""

    tenant_id: UUID
    tenant_name: str
    tenant_slug: str
    role: str
    is_active: bool
    version: int = Field(ge=1)


class MeResponse(ApiModel):
    """Current seller identity and active tenant memberships."""

    user: UserResponse
    memberships: list[TenantMembershipResponse]


class TenantContextResponse(ApiModel):
    """Selected tenant context for the authenticated seller."""

    tenant_id: UUID
    tenant_name: str
    tenant_slug: str
    role: str
    permissions: list[str]
