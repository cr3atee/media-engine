from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.catalog.categories import category_by_code
from app.database.repository_scope import create_postgres_repository_scope
from app.domain.admin_actions import AdminAction, AdminResourceType
from app.domain.tenancy import Tenant
from app.models.canonical_product import CanonicalProduct
from app.repositories.postgres import PostgresAdminActionRepository
from app.repositories.provider import RepositoryProvider, create_postgres_provider
from app.services.admin_mutations import AdminCommandContext
from app.services.canonical_product_categories import (
    CanonicalProductCategoryService,
    ChangeProductCategoryCommand,
    ProductCategoryChangeError,
)

DATABASE_URL = os.getenv("EPIC25_CATEGORY_TEST_DATABASE_URL", "")


class FailingAuditRepository(PostgresAdminActionRepository):
    """Inject an audit failure after the product category update."""

    async def append(self, action: AdminAction) -> AdminAction:
        raise RuntimeError("controlled postgres audit failure")


@pytest.mark.skipif(not DATABASE_URL, reason="isolated category PostgreSQL URL not set")
def test_postgres_category_correction_lifecycle() -> None:
    """Exercise atomicity, conflicts, isolation, concurrency and fresh sessions."""
    url = make_url(DATABASE_URL)
    assert url.drivername == "postgresql+asyncpg"
    assert url.host in {"localhost", "127.0.0.1", "::1"}
    assert (url.database or "").startswith("epic25_category_verify_")

    async def scenario() -> None:
        engine = create_async_engine(DATABASE_URL)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        scope = create_postgres_repository_scope(sessions)
        tenant_id = uuid4()
        product_id = uuid4()
        rollback_id = uuid4()
        concurrent_id = uuid4()
        now = datetime.now(UTC)
        product = CanonicalProduct(
            id=product_id,
            tenant_id=tenant_id,
            name="Monthly subscription Key",
            category=category_by_code("keys").name,
            aliases=("Monthly key",),
        )
        command = ChangeProductCategoryCommand(
            tenant_id=tenant_id,
            product_id=product_id,
            expected_version=1,
            expected_category="keys",
            category="subscriptions",
            reason="Operator correction",
        )
        context = AdminCommandContext(
            tenant_id=tenant_id,
            actor_id="postgres-test",
            elevated=True,
            request_id=str(uuid4()),
            idempotency_key=str(uuid4()),
        )
        try:
            async with scope() as repositories:
                await repositories.tenants.create(
                    Tenant(
                        id=tenant_id,
                        name="Category verifier",
                        slug=f"category-{tenant_id}",
                        created_at=now,
                        updated_at=now,
                    )
                )
                for item_id in (product_id, rollback_id, concurrent_id):
                    await repositories.canonical_products.save(
                        replace(product, id=item_id)
                    )
            service = CanonicalProductCategoryService(scope)
            action = await service.change(command, context)
            assert action == await service.change(command, context)
            with pytest.raises(
                ProductCategoryChangeError, match="idempotency_conflict"
            ):
                await service.change(replace(command, category="accounts"), context)
            with pytest.raises(
                ProductCategoryChangeError, match="category_version_conflict"
            ):
                await service.change(
                    command, replace(context, idempotency_key=str(uuid4()))
                )
            foreign = uuid4()
            with pytest.raises(ProductCategoryChangeError, match="product_not_found"):
                await service.change(
                    replace(command, tenant_id=foreign),
                    replace(context, tenant_id=foreign),
                )

            @asynccontextmanager
            async def failing_scope() -> AsyncIterator[RepositoryProvider]:
                async with sessions() as session, session.begin():
                    repositories = create_postgres_provider(session)
                    repositories.admin_actions = FailingAuditRepository(session)
                    yield repositories

            with pytest.raises(RuntimeError, match="controlled postgres audit failure"):
                await CanonicalProductCategoryService(failing_scope).change(
                    replace(command, product_id=rollback_id),
                    replace(context, idempotency_key=str(uuid4())),
                )
            outcomes = await asyncio.gather(
                service.change(
                    replace(command, product_id=concurrent_id),
                    replace(context, idempotency_key=str(uuid4())),
                ),
                service.change(
                    replace(command, product_id=concurrent_id, category="accounts"),
                    replace(context, idempotency_key=str(uuid4())),
                ),
                return_exceptions=True,
            )
            assert sum(isinstance(item, AdminAction) for item in outcomes) == 1
            assert (
                sum(isinstance(item, ProductCategoryChangeError) for item in outcomes)
                == 1
            )
        finally:
            await engine.dispose()

        fresh = create_async_engine(DATABASE_URL)
        fresh_scope = create_postgres_repository_scope(
            async_sessionmaker(fresh, expire_on_commit=False)
        )
        try:
            async with fresh_scope() as repositories:
                assert await repositories.canonical_products.get_by_id(
                    product_id
                ) == replace(product, category=category_by_code("subscriptions").name)
                assert await repositories.canonical_products.get_by_id(
                    rollback_id
                ) == replace(product, id=rollback_id)
                assert not await repositories.admin_actions.list_for_resource(
                    AdminResourceType.CANONICAL_PRODUCT, rollback_id
                )
                trail = await repositories.admin_actions.list_for_resource(
                    AdminResourceType.CANONICAL_PRODUCT, product_id
                )
                assert len(trail) == 1 and trail[0].id == action.id
                assert (
                    len(
                        await repositories.admin_actions.list_for_resource(
                            AdminResourceType.CANONICAL_PRODUCT, concurrent_id
                        )
                    )
                    == 1
                )
            assert (
                await CanonicalProductCategoryService(fresh_scope).change(
                    command, context
                )
                == action
            )
        finally:
            await fresh.dispose()

    asyncio.run(scenario())
