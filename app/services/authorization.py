from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.domain.auth import (
    ROLE_PERMISSIONS,
    AuthenticatedPrincipal,
    Permission,
    TenantContext,
)
from app.domain.tenancy import Membership, Tenant, User
from app.services.repository_scope import RepositoryScopeFactory


class AuthorizationError(Exception):
    """Safe authorization failure with stable public status."""

    def __init__(self, code: str, message: str, *, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass(slots=True, frozen=True, kw_only=True)
class TenantMembershipView:
    """Current membership plus tenant details for `/api/v1/me`."""

    tenant: Tenant
    membership: Membership


@dataclass(slots=True, frozen=True, kw_only=True)
class PrincipalProfile:
    """Current user profile with active tenant memberships."""

    user: User
    memberships: tuple[TenantMembershipView, ...]


class AuthorizationService:
    """Resolve tenant context and enforce centralized role permissions."""

    def __init__(self, repository_scope_factory: RepositoryScopeFactory) -> None:
        """Bind authorization checks to repository scopes."""
        self._repository_scope_factory = repository_scope_factory

    async def get_profile(
        self,
        principal: AuthenticatedPrincipal,
    ) -> PrincipalProfile:
        """Return the current user and active memberships."""
        async with self._repository_scope_factory() as repositories:
            user = await repositories.users.get_by_id(principal.user_id)
            if user is None or not user.enabled:
                raise AuthorizationError(
                    "account_disabled",
                    "User account is disabled.",
                    status_code=403,
                )
            memberships = []
            for membership in await repositories.memberships.list_for_user(user.id):
                if not membership.is_active:
                    continue
                tenant = await repositories.tenants.get_by_id(membership.tenant_id)
                if tenant is not None and tenant.is_active:
                    memberships.append(
                        TenantMembershipView(
                            tenant=tenant,
                            membership=membership,
                        )
                    )
        return PrincipalProfile(user=user, memberships=tuple(memberships))

    async def require_tenant_context(
        self,
        principal: AuthenticatedPrincipal,
        tenant_id: UUID,
        permission: Permission,
    ) -> TenantContext:
        """Resolve and validate one tenant context for a permission."""
        async with self._repository_scope_factory() as repositories:
            user = await repositories.users.get_by_id(principal.user_id)
            tenant = await repositories.tenants.get_by_id(tenant_id)
            membership = await repositories.memberships.get_by_user_and_tenant(
                principal.user_id,
                tenant_id,
            )
            if user is None or not user.enabled:
                raise AuthorizationError(
                    "account_disabled",
                    "User account is disabled.",
                    status_code=403,
                )
            if tenant is None or not tenant.is_active:
                raise _tenant_not_found()
            if membership is None or not membership.is_active:
                raise _tenant_not_found()
            if permission not in ROLE_PERMISSIONS[membership.role]:
                raise AuthorizationError(
                    "permission_denied",
                    "Tenant permission is required.",
                    status_code=403,
                )
        return TenantContext(
            principal=principal,
            user=user,
            tenant=tenant,
            membership=membership,
        )


def _tenant_not_found() -> AuthorizationError:
    return AuthorizationError(
        "tenant_not_found",
        "Tenant was not found.",
        status_code=404,
    )
