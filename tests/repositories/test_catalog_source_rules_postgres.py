"""PostgreSQL verification for durable catalog source classification rules."""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.catalog.hierarchy import CatalogSourceRule
from app.domain.marketplace_integrations import (
    MarketplaceIntegration,
    MarketplaceIntegrationStatus,
)
from app.domain.tenancy import Tenant
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.postgres.postgres_catalog_source_rules import (
    PostgresCatalogSourceRuleRepository,
)
from app.repositories.postgres.postgres_marketplace_integrations import (
    PostgresMarketplaceIntegrationRepository,
)
from app.repositories.postgres.postgres_tenants import PostgresTenantRepository

DATABASE_URL = os.getenv("CATALOG_SOURCE_RULE_TEST_DATABASE_URL")
TENANT_A = UUID("10000000-0000-4000-8000-000000000001")
TENANT_B = UUID("10000000-0000-4000-8000-000000000002")
INTEGRATION_A = UUID("20000000-0000-4000-8000-000000000001")
INTEGRATION_B = UUID("20000000-0000-4000-8000-000000000002")
NOW = datetime(2026, 10, 30, 10, 0, tzinfo=UTC)


def test_catalog_source_rule_persistence_isolation_and_rollback() -> None:
    """Rules survive restart and remain tenant/integration scoped and atomic."""
    if not DATABASE_URL:
        pytest.skip("Requires CATALOG_SOURCE_RULE_TEST_DATABASE_URL")
    url = make_url(DATABASE_URL)
    assert url.drivername == "postgresql+asyncpg"
    assert url.host in {"127.0.0.1", "localhost"}
    assert url.database == "mediaengine_catalog_source_rules_test"

    async def scenario() -> None:
        engine = create_async_engine(url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                tenants = PostgresTenantRepository(session)
                integrations = PostgresMarketplaceIntegrationRepository(session)
                await tenants.create(_tenant(TENANT_A, "catalog-a"))
                await tenants.create(_tenant(TENANT_B, "catalog-b"))
                await integrations.save(
                    _integration(INTEGRATION_A, TENANT_A, "minecraft")
                )
                await integrations.save(
                    _integration(INTEGRATION_B, TENANT_A, "fortnite")
                )
                await session.commit()

            original = _rule()
            second_integration = _rule(
                number=2,
                integration_id=INTEGRATION_B,
                section_code="accounts",
            )
            async with factory() as session:
                repository = PostgresCatalogSourceRuleRepository(session)
                await repository.save(original)
                await repository.save(second_integration)
                await session.commit()

            async with factory() as session:
                repository = PostgresCatalogSourceRuleRepository(session)
                stored = await repository.get_by_source(
                    TENANT_A,
                    INTEGRATION_A,
                    "PLAYEROK",
                    "fortnite-products",
                )
                assert stored == original
                assert (
                    await repository.get_by_source(
                        TENANT_B,
                        INTEGRATION_A,
                        "playerok",
                        "fortnite-products",
                    )
                    is None
                )
                assert tuple(await repository.list_by_tenant(TENANT_A)) == (
                    original,
                    second_integration,
                )

            updated = replace(
                original,
                source_category_name="Fortnite products",
                section_code="items",
                updated_at=original.updated_at + timedelta(minutes=5),
                version=2,
            )
            async with factory() as session:
                repository = PostgresCatalogSourceRuleRepository(session)
                await repository.save(updated)
                await session.commit()

            async with factory() as session:
                stored = await PostgresCatalogSourceRuleRepository(
                    session
                ).get_by_source(
                    TENANT_A,
                    INTEGRATION_A,
                    "playerok",
                    "fortnite-products",
                )
                assert stored == updated

            async with factory() as session:
                repository = PostgresCatalogSourceRuleRepository(session)
                with pytest.raises(RepositoryIdentityConflictError):
                    await repository.save(_rule(number=3))
                await session.rollback()

            rollback_rule = _rule(number=4, source_category_id="rollback")
            async with factory() as session:
                await PostgresCatalogSourceRuleRepository(session).save(rollback_rule)
                await session.rollback()

            async with factory() as session:
                assert (
                    await PostgresCatalogSourceRuleRepository(session).get_by_source(
                        TENANT_A,
                        INTEGRATION_A,
                        "playerok",
                        "rollback",
                    )
                    is None
                )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def _tenant(tenant_id: UUID, slug: str) -> Tenant:
    return Tenant(
        id=tenant_id,
        name=slug.title(),
        slug=slug,
        created_at=NOW,
        updated_at=NOW,
    )


def _integration(
    integration_id: UUID,
    tenant_id: UUID,
    source_name: str,
) -> MarketplaceIntegration:
    return MarketplaceIntegration(
        id=integration_id,
        tenant_id=tenant_id,
        marketplace="playerok",
        display_name=f"Playerok {source_name}",
        enabled=True,
        status=MarketplaceIntegrationStatus.ACTIVE,
        source_url=f"https://playerok.com/catalog/{source_name}",
        created_at=NOW,
        updated_at=NOW,
    )


def _rule(
    *,
    number: int = 1,
    integration_id: UUID = INTEGRATION_A,
    source_category_id: str = "fortnite-products",
    section_code: str = "v-bucks",
) -> CatalogSourceRule:
    created_at = NOW + timedelta(minutes=number)
    return CatalogSourceRule(
        id=UUID(int=40_000 + number),
        tenant_id=TENANT_A,
        integration_id=integration_id,
        marketplace="playerok",
        source_category_id=source_category_id,
        source_category_name="Fortnite products",
        hub_code="fortnite",
        section_code=section_code,
        created_at=created_at,
        updated_at=created_at,
    )
