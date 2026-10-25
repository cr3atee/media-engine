"""Product role commands must not infer platform access from tenant membership."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.domain.auth import ActorType, AuthenticatedPrincipal
from app.domain.product_access import (
    LastProductAdminError,
    ProductRole,
    ProductRoleAction,
)
from app.domain.tenancy import User
from app.repositories.memory.memory_product_role_actions import (
    MemoryProductRoleActionRepository,
)
from app.repositories.provider import RepositoryProvider, create_memory_provider
from app.services.product_roles import ProductRoleError, ProductRoleService
from app.services.repository_scope import create_memory_repository_scope
from tests.repositories.contracts.factories import run_async


def principal(user_id: UUID) -> AuthenticatedPrincipal:
    now = datetime.now(UTC)
    return AuthenticatedPrincipal(
        actor_type=ActorType.USER,
        user_id=user_id,
        session_id=uuid4(),
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )


async def seed(provider: RepositoryProvider) -> tuple[UUID, UUID]:
    ids = (uuid4(), uuid4())
    now = datetime.now(UTC)
    for user_id in ids:
        await provider.users.create(
            User(
                id=user_id,
                email=f"{user_id}@example.test",
                created_at=now,
                updated_at=now,
            )
        )
    return ids


def test_bootstrap_assign_replay_audit_and_last_admin() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        admin, target = await seed(provider)
        service = ProductRoleService(create_memory_repository_scope(provider))
        boot = await service.bootstrap(
            user_id=admin,
            expected_version=1,
            reason="Operator bootstrap",
            idempotency_key="bootstrap",
        )
        assert boot.actor_user_id is None and boot.actor_key == "bootstrap"
        assert (
            await service.bootstrap(
                user_id=admin,
                expected_version=1,
                reason="Operator bootstrap",
                idempotency_key="bootstrap",
            )
            == boot
        )
        with pytest.raises(ProductRoleError, match="already_initialized"):
            await service.bootstrap(
                user_id=target,
                expected_version=1,
                reason="Other bootstrap",
                idempotency_key="other",
            )
        with pytest.raises(ProductRoleError, match="last_product_admin"):
            await service.assign(
                principal(admin),
                user_id=admin,
                role=ProductRole.USER,
                expected_version=2,
                reason="Demotion",
                idempotency_key="demote",
            )
        with pytest.raises(LastProductAdminError):
            await provider.users.set_enabled(admin, False, 2)
        action = await service.assign(
            principal(admin),
            user_id=target,
            role=ProductRole.PARTNER,
            expected_version=1,
            reason="Partner onboarding",
            idempotency_key="partner",
        )
        assert (
            action.previous_role is ProductRole.USER and action.resulting_version == 2
        )
        assert (
            await service.assign(
                principal(admin),
                user_id=target,
                role=ProductRole.PARTNER,
                expected_version=1,
                reason="Partner onboarding",
                idempotency_key="partner",
            )
            == action
        )
        with pytest.raises(ProductRoleError, match="idempotency_conflict"):
            await service.assign(
                principal(admin),
                user_id=target,
                role=ProductRole.MODERATOR,
                expected_version=2,
                reason="Changed command",
                idempotency_key="partner",
            )
        with pytest.raises(ProductRoleError, match="version_conflict"):
            await service.assign(
                principal(admin),
                user_id=target,
                role=ProductRole.MODERATOR,
                expected_version=1,
                reason="Stale version",
                idempotency_key="stale",
            )
        with pytest.raises(ProductRoleError, match="product_admin_required"):
            await service.assign(
                principal(target),
                user_id=target,
                role=ProductRole.ADMIN,
                expected_version=2,
                reason="Self escalation",
                idempotency_key="bad",
            )
        assert await service.audit(principal(admin), target) == (action,)
        promoted = await service.assign(
            principal(admin),
            user_id=target,
            role=ProductRole.ADMIN,
            expected_version=2,
            reason="Second admin",
            idempotency_key="promote",
        )
        assert promoted.resulting_version == 3
        await service.assign(
            principal(target),
            user_id=admin,
            role=ProductRole.USER,
            expected_version=2,
            reason="Retire admin",
            idempotency_key="retire",
        )
        with pytest.raises(ProductRoleError, match="product_admin_required"):
            await service.audit(principal(admin), target)

    run_async(scenario())


def test_memory_role_and_audit_rollback_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        admin, target = await seed(provider)
        scope = create_memory_repository_scope(provider)
        service = ProductRoleService(scope)
        await service.bootstrap(
            user_id=admin,
            expected_version=1,
            reason="Bootstrap",
            idempotency_key="boot",
        )
        original = type(provider.product_role_actions).append

        async def fail_after_append(
            self: MemoryProductRoleActionRepository, action: ProductRoleAction
        ) -> None:
            await original(self, action)
            raise RuntimeError("Injected audit failure")

        with monkeypatch.context() as patch:
            patch.setattr(
                type(provider.product_role_actions), "append", fail_after_append
            )
            with pytest.raises(RuntimeError, match="Injected"):
                await service.assign(
                    principal(admin),
                    user_id=target,
                    role=ProductRole.PARTNER,
                    expected_version=1,
                    reason="Rollback",
                    idempotency_key="rollback",
                )
        assert type(provider.product_role_actions).append is original
        user = await provider.users.get_by_id(target)
        assert user and user.product_role is ProductRole.USER and user.version == 1
        assert await provider.product_role_actions.list_for_user(target) == ()

    run_async(scenario())


def test_invalid_role_and_privileged_creation_rejected() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        now = datetime.now(UTC)
        with pytest.raises(ValueError, match="New users"):
            await provider.users.create(
                User(
                    id=uuid4(),
                    email="admin@example.test",
                    created_at=now,
                    updated_at=now,
                    product_role=ProductRole.ADMIN,
                )
            )
        admin, target = await seed(provider)
        service = ProductRoleService(create_memory_repository_scope(provider))
        await service.bootstrap(
            user_id=admin,
            expected_version=1,
            reason="Bootstrap",
            idempotency_key="boot",
        )
        with pytest.raises(ProductRoleError, match="invalid_role_command"):
            await service.assign(
                principal(admin),
                user_id=target,
                role=ProductRole.PARTNER,
                expected_version=1,
                reason="   ",
                idempotency_key="blank",
            )

    run_async(scenario())
