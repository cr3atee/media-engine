"""Run only against an explicitly supplied disposable product_access_test database."""

import asyncio
import os
from dataclasses import replace
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.repository_scope import create_postgres_repository_scope
from app.domain.product_access import (
    LastProductAdminError,
    ProductRole,
    ProductRoleAction,
)
from app.repositories.postgres.postgres_product_role_actions import (
    PostgresProductRoleActionRepository,
)
from app.services.product_roles import ProductRoleError, ProductRoleService
from tests.repositories.contracts.factories import run_async
from tests.services.test_product_roles import principal, seed


def test_postgres_roles_atomicity_concurrency_and_immutable_audit() -> None:
    raw_url = os.environ.get("PRODUCT_ACCESS_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("Requires a disposable PRODUCT_ACCESS_TEST_DATABASE_URL")
    url = make_url(raw_url)
    assert url.drivername == "postgresql+asyncpg"
    assert url.host in {"127.0.0.1", "localhost"}
    assert url.database == "product_access_test"

    async def scenario() -> None:
        engine = create_async_engine(url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        scope = create_postgres_repository_scope(factory)
        service = ProductRoleService(scope)
        try:
            async with scope() as repositories:
                # No cleanup or mutation of an already initialized database is allowed.
                assert not await repositories.users.list_product_admins(), (
                    "Use a fresh test database"
                )
                admin, target = await seed(repositories)
            boot = await service.bootstrap(
                user_id=admin,
                expected_version=1,
                reason="Test bootstrap",
                idempotency_key="bootstrap",
            )
            assert boot.previous_role is ProductRole.USER
            assert (
                await service.bootstrap(
                    user_id=admin,
                    expected_version=1,
                    reason="Test bootstrap",
                    idempotency_key="bootstrap",
                )
                == boot
            )
            with pytest.raises(ProductRoleError, match="already_initialized"):
                await service.bootstrap(
                    user_id=target,
                    expected_version=1,
                    reason="Second bootstrap",
                    idempotency_key="bootstrap-other",
                )
            with pytest.raises(ProductRoleError, match="product_admin_required"):
                await service.assign(
                    principal(target),
                    user_id=target,
                    role=ProductRole.ADMIN,
                    expected_version=1,
                    reason="Escalate",
                    idempotency_key="escalate",
                )

            async def change(role: ProductRole, key: str) -> ProductRoleAction | str:
                try:
                    return await service.assign(
                        principal(admin),
                        user_id=target,
                        role=role,
                        expected_version=1,
                        reason="Concurrent assignment",
                        idempotency_key=key,
                    )
                except ProductRoleError as exc:
                    return exc.code

            results = await asyncio.wait_for(
                asyncio.gather(
                    change(ProductRole.PARTNER, "partner"),
                    change(ProductRole.MODERATOR, "moderator"),
                ),
                timeout=15,
            )
            actions = [
                result for result in results if isinstance(result, ProductRoleAction)
            ]
            assert len(actions) == 1 and "version_conflict" in results
            action = actions[0]
            assert (
                await service.assign(
                    principal(admin),
                    user_id=target,
                    role=action.resulting_role,
                    expected_version=1,
                    reason="Concurrent assignment",
                    idempotency_key=action.idempotency_key,
                )
                == action
            )
            with pytest.raises(ProductRoleError, match="idempotency_conflict"):
                await service.assign(
                    principal(admin),
                    user_id=target,
                    role=ProductRole.ADMIN,
                    expected_version=2,
                    reason="Different fingerprint",
                    idempotency_key=action.idempotency_key,
                )
            async with scope() as repositories:
                user = await repositories.users.get_by_id(target)
                assert (
                    user
                    and user.product_role is action.resulting_role
                    and user.version == 2
                )
                assert await repositories.product_role_actions.list_for_user(
                    target
                ) == (action,)

            original_append = PostgresProductRoleActionRepository.append

            async def failing_append(
                self: PostgresProductRoleActionRepository, entry: ProductRoleAction
            ) -> None:
                await original_append(self, entry)
                raise RuntimeError("Injected after audit flush")

            with patch.object(
                PostgresProductRoleActionRepository, "append", failing_append
            ):
                with pytest.raises(RuntimeError, match="Injected"):
                    await service.assign(
                        principal(admin),
                        user_id=target,
                        role=ProductRole.ADMIN,
                        expected_version=2,
                        reason="Rollback",
                        idempotency_key="rollback",
                    )
            async with scope() as repositories:
                user = await repositories.users.get_by_id(target)
                assert (
                    user
                    and user.version == 2
                    and user.product_role is action.resulting_role
                )
                assert (
                    await repositories.product_role_actions.get_replay(
                        str(admin), "rollback"
                    )
                    is None
                )

            # Uniqueness and append-only guarantees apply even to direct SQL writes.
            with pytest.raises(IntegrityError):
                async with scope() as repositories:
                    await repositories.product_role_actions.append(
                        replace(action, id=uuid4())
                    )
            for statement in (
                "UPDATE product_role_actions SET reason = 'tampered'",
                "DELETE FROM product_role_actions",
                "TRUNCATE product_role_actions",
            ):
                with pytest.raises(DBAPIError, match="immutable"):
                    async with engine.begin() as connection:
                        await connection.execute(text(statement))
            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.execute(
                        text("UPDATE users SET product_role = 'root' WHERE id = :id"),
                        {"id": target},
                    )

            await service.assign(
                principal(admin),
                user_id=target,
                role=ProductRole.ADMIN,
                expected_version=2,
                reason="Second admin",
                idempotency_key="second-admin",
            )

            async def demote(user_id: UUID, version: int) -> ProductRoleAction | str:
                try:
                    return await service.assign(
                        principal(user_id),
                        user_id=user_id,
                        role=ProductRole.USER,
                        expected_version=version,
                        reason="Concurrent retirement",
                        idempotency_key="retire-self",
                    )
                except ProductRoleError as exc:
                    return exc.code

            demotions = await asyncio.wait_for(
                asyncio.gather(demote(admin, 2), demote(target, 3)), timeout=15
            )
            assert (
                sum(isinstance(result, ProductRoleAction) for result in demotions) == 1
            )
            assert "last_product_admin" in demotions
            async with scope() as repositories:
                admins = await repositories.users.list_product_admins()
                assert len(admins) == 1 and admins[0].enabled
                remaining = admins[0]
                retired_id = target if remaining.id == admin else admin
                retired = await repositories.users.get_by_id(retired_id)
                assert retired is not None
            with pytest.raises(ProductRoleError, match="product_admin_required"):
                await service.audit(principal(retired_id), target)
            with pytest.raises(LastProductAdminError):
                async with scope() as repositories:
                    await repositories.users.set_enabled(
                        remaining.id, False, remaining.version
                    )
            restored = await service.assign(
                principal(remaining.id),
                user_id=retired_id,
                role=ProductRole.ADMIN,
                expected_version=retired.version,
                reason="Restore second admin",
                idempotency_key="restore",
            )

            async def disable() -> str:
                try:
                    async with scope() as repositories:
                        result = await repositories.users.set_enabled(
                            retired_id, False, restored.resulting_version
                        )
                        assert result and not result.enabled
                    return "disabled"
                except LastProductAdminError:
                    return "last_product_admin"

            mixed = await asyncio.wait_for(
                asyncio.gather(demote(remaining.id, remaining.version), disable()),
                timeout=15,
            )
            assert "last_product_admin" in mixed
            assert (
                sum(
                    isinstance(result, ProductRoleAction) or result == "disabled"
                    for result in mixed
                )
                == 1
            )
            # Rebuild the pool to verify durable state, not an identity-map cache.
            await engine.dispose()
            fresh_engine = create_async_engine(url)
            try:
                fresh_scope = create_postgres_repository_scope(
                    async_sessionmaker(fresh_engine, expire_on_commit=False)
                )
                async with fresh_scope() as repositories:
                    assert (
                        len(
                            [
                                u
                                for u in await repositories.users.list_product_admins()
                                if u.enabled
                            ]
                        )
                        == 1
                    )
                    assert (
                        await repositories.product_role_actions.get_replay(
                            "bootstrap", "bootstrap"
                        )
                        == boot
                    )
                    assert (
                        await repositories.product_role_actions.get_replay(
                            str(admin), action.idempotency_key
                        )
                        == action
                    )
            finally:
                await fresh_engine.dispose()
        finally:
            await engine.dispose()

    run_async(scenario())
