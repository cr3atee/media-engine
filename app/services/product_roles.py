"""Audited product role changes, independent of all tenant role assignments."""

from uuid import UUID, uuid4

from app.domain.auth import ActorType, AuthenticatedPrincipal
from app.domain.identity import hash_identity_fields
from app.domain.product_access import (
    LastProductAdminError,
    ProductRole,
    ProductRoleAction,
)
from app.domain.tenancy import User, utc_now
from app.repositories.provider import RepositoryProvider
from app.services.repository_scope import RepositoryScopeFactory


class ProductRoleError(Exception):
    """Stable, safe administrative error without leaking target account details."""

    def __init__(self, code: str, status: int) -> None:
        self.code = code
        self.status = status
        super().__init__(code)


class ProductRoleService:
    """Authorize, serialize and audit one role command in a single transaction."""

    def __init__(self, scope_factory: RepositoryScopeFactory) -> None:
        self._scope_factory = scope_factory

    async def assign(
        self,
        principal: AuthenticatedPrincipal,
        *,
        user_id: UUID,
        role: ProductRole,
        expected_version: int,
        reason: str,
        idempotency_key: str,
    ) -> ProductRoleAction:
        """Require a live product-admin grant; bearer role claims are not trusted."""
        async with self._scope_factory() as repositories:
            await repositories.users.lock_role_changes()
            await self._require_admin(repositories, principal)
            return await self._apply(
                repositories,
                actor_user_id=principal.user_id,
                user_id=user_id,
                role=role,
                expected_version=expected_version,
                reason=reason,
                idempotency_key=idempotency_key,
            )

    async def bootstrap(
        self, *, user_id: UUID, expected_version: int, reason: str, idempotency_key: str
    ) -> ProductRoleAction:
        """Trusted operator-only entry point; deliberately not exposed via HTTP."""
        async with self._scope_factory() as repositories:
            await repositories.users.lock_role_changes()
            return await self._apply(
                repositories,
                actor_user_id=None,
                user_id=user_id,
                role=ProductRole.ADMIN,
                expected_version=expected_version,
                reason=reason,
                idempotency_key=idempotency_key,
            )

    async def audit(
        self, principal: AuthenticatedPrincipal, user_id: UUID, limit: int = 100
    ) -> tuple[ProductRoleAction, ...]:
        """Only current enabled product admins may inspect role assignment history."""
        async with self._scope_factory() as repositories:
            await self._require_admin(repositories, principal)
            return await repositories.product_role_actions.list_for_user(user_id, limit)

    async def get_user(self, principal: AuthenticatedPrincipal, user_id: UUID) -> User:
        """Read the current role and optimistic version only after authorization."""
        async with self._scope_factory() as repositories:
            await self._require_admin(repositories, principal)
            user = await repositories.users.get_by_id(user_id)
            if user is None:
                raise ProductRoleError("role_target_unavailable", 404)
            return user

    async def _require_admin(
        self, repositories: RepositoryProvider, principal: AuthenticatedPrincipal
    ) -> None:
        user = await repositories.users.get_by_id(principal.user_id)
        if (
            principal.actor_type is not ActorType.USER
            or user is None
            or not user.enabled
            or user.product_role is not ProductRole.ADMIN
        ):
            raise ProductRoleError("product_admin_required", 403)

    async def _apply(
        self,
        repositories: RepositoryProvider,
        *,
        actor_user_id: UUID | None,
        user_id: UUID,
        role: ProductRole,
        expected_version: int,
        reason: str,
        idempotency_key: str,
    ) -> ProductRoleAction:
        reason = reason.strip()
        idempotency_key = idempotency_key.strip()
        if (
            not isinstance(role, ProductRole)
            or expected_version < 1
            or not 1 <= len(reason) <= 1000
            or not 1 <= len(idempotency_key) <= 128
        ):
            raise ProductRoleError("invalid_role_command", 422)
        actor_key = str(actor_user_id) if actor_user_id else "bootstrap"
        fingerprint = hash_identity_fields(
            actor_key, str(user_id), role.value, str(expected_version), reason
        )
        replay = await repositories.product_role_actions.get_replay(
            actor_key, idempotency_key
        )
        if replay:
            if replay.fingerprint != fingerprint:
                raise ProductRoleError("idempotency_conflict", 409)
            return replay
        if actor_user_id is None and await repositories.users.list_product_admins():
            raise ProductRoleError("product_admin_already_initialized", 409)
        target = await repositories.users.get_by_id(user_id)
        if target is None or not target.enabled:
            raise ProductRoleError("role_target_unavailable", 404)
        if target.version != expected_version:
            raise ProductRoleError("version_conflict", 409)
        if target.product_role is role:
            raise ProductRoleError("product_role_unchanged", 409)
        try:
            updated = await repositories.users.set_product_role(
                user_id, role, expected_version
            )
        except LastProductAdminError as exc:
            raise ProductRoleError("last_product_admin", 409) from exc
        if updated is None:
            raise ProductRoleError("version_conflict", 409)
        action = ProductRoleAction(
            id=uuid4(),
            user_id=user_id,
            actor_user_id=actor_user_id,
            actor_key=actor_key,
            previous_role=target.product_role,
            resulting_role=role,
            expected_version=expected_version,
            resulting_version=updated.version,
            reason=reason,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            created_at=utc_now(),
        )
        await repositories.product_role_actions.append(action)
        return action
