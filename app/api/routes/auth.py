from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies import (
    get_authentication_service,
    get_authorization_service,
    map_authentication_error,
    map_authorization_error,
    require_seller_principal,
)
from app.api.schemas.auth import (
    AcceptedResponse,
    LoginRequest,
    LogoutRequest,
    MeResponse,
    PasswordResetCompleteRequest,
    PasswordResetRequest,
    RefreshTokenRequest,
    TenantContextResponse,
    TenantMembershipResponse,
    TokenResponse,
    UserResponse,
)
from app.domain.auth import ROLE_PERMISSIONS, AuthenticatedPrincipal, Permission
from app.services.authentication import AuthenticationError, AuthenticationService
from app.services.authorization import AuthorizationError, AuthorizationService

router = APIRouter(prefix="/api/v1", tags=["seller-auth"])


@router.post("/auth/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> TokenResponse:
    """Authenticate a seller and create a refresh-token session."""
    try:
        result = await service.login(email=request.email, password=request.password)
    except AuthenticationError as exc:
        raise map_authentication_error(exc) from exc
    return TokenResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        token_type=result.token_type,
        expires_in=result.expires_in,
    )


@router.post("/auth/refresh", response_model=TokenResponse)
async def refresh(
    request: RefreshTokenRequest,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> TokenResponse:
    """Rotate a refresh token and return a fresh token pair."""
    try:
        result = await service.refresh(refresh_token=request.refresh_token)
    except AuthenticationError as exc:
        raise map_authentication_error(exc) from exc
    return TokenResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        token_type=result.token_type,
        expires_in=result.expires_in,
    )


@router.post("/auth/logout", response_model=AcceptedResponse)
async def logout(
    request: LogoutRequest,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> AcceptedResponse:
    """Revoke a refresh-token session without leaking token state."""
    await service.logout(refresh_token=request.refresh_token)
    return AcceptedResponse(status="ok")


@router.post("/auth/password-reset/request", response_model=AcceptedResponse)
async def request_password_reset(
    request: PasswordResetRequest,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> AcceptedResponse:
    """Accept a reset request without revealing whether the email exists."""
    try:
        await service.request_password_reset(email=request.email)
    except AuthenticationError as exc:
        raise map_authentication_error(exc) from exc
    return AcceptedResponse(status="accepted")


@router.post("/auth/password-reset/complete", response_model=AcceptedResponse)
async def complete_password_reset(
    request: PasswordResetCompleteRequest,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> AcceptedResponse:
    """Consume a password reset token and revoke existing sessions."""
    try:
        await service.complete_password_reset(
            reset_token=request.reset_token,
            new_password=request.new_password,
        )
    except AuthenticationError as exc:
        raise map_authentication_error(exc) from exc
    return AcceptedResponse(status="ok")


@router.get("/me", response_model=MeResponse)
async def me(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_seller_principal)],
    service: Annotated[AuthorizationService, Depends(get_authorization_service)],
) -> MeResponse:
    """Return the authenticated seller identity and active memberships."""
    try:
        profile = await service.get_profile(principal)
    except AuthorizationError as exc:
        raise map_authorization_error(exc) from exc
    return MeResponse(
        user=UserResponse(
            id=profile.user.id,
            email=profile.user.email,
            display_name=profile.user.display_name,
            enabled=profile.user.enabled,
        ),
        memberships=[
            TenantMembershipResponse(
                tenant_id=item.tenant.id,
                tenant_name=item.tenant.name,
                tenant_slug=item.tenant.slug,
                role=item.membership.role.value,
                is_active=item.membership.is_active,
                version=item.membership.version,
            )
            for item in profile.memberships
        ],
    )


@router.get(
    "/tenants/{tenant_id}/context",
    response_model=TenantContextResponse,
)
async def tenant_context(
    tenant_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_seller_principal)],
    service: Annotated[AuthorizationService, Depends(get_authorization_service)],
) -> TenantContextResponse:
    """Resolve one explicit tenant context for the authenticated seller."""
    try:
        context = await service.require_tenant_context(
            principal,
            tenant_id,
            Permission.DASHBOARD_READ,
        )
    except AuthorizationError as exc:
        raise map_authorization_error(exc) from exc
    permissions = sorted(
        permission.value for permission in ROLE_PERMISSIONS[context.membership.role]
    )
    return TenantContextResponse(
        tenant_id=context.tenant.id,
        tenant_name=context.tenant.name,
        tenant_slug=context.tenant.slug,
        role=context.membership.role.value,
        permissions=permissions,
    )
