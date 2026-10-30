"""PostgreSQL verification for persisted offer catalog classification."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.catalog.hierarchy import CatalogSourceRule
from app.domain.marketplace_integrations import (
    MarketplaceIntegration,
    MarketplaceIntegrationStatus,
)
from app.domain.tenancy import LEGACY_TENANT_ID
from app.parsers.models import ParsedOffer
from app.repositories.postgres.postgres_catalog_source_rules import (
    PostgresCatalogSourceRuleRepository,
)
from app.repositories.postgres.postgres_marketplace_integrations import (
    PostgresMarketplaceIntegrationRepository,
)
from app.repositories.postgres.postgres_offers import PostgresOfferRepository

DATABASE_URL = os.getenv("OFFER_CATALOG_CLASSIFICATION_TEST_DATABASE_URL")
INTEGRATION_ID = UUID("25000000-0000-4000-8000-000000000001")
RULE_ID = UUID("25000000-0000-4000-8000-000000000002")
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


def test_offer_catalog_classification_persistence_and_constraints() -> None:
    """Classification survives restart, preserves evidence, and rolls back."""
    if not DATABASE_URL:
        pytest.skip("Requires OFFER_CATALOG_CLASSIFICATION_TEST_DATABASE_URL")
    url = make_url(DATABASE_URL)
    assert url.drivername == "postgresql+asyncpg"
    assert url.host in {"127.0.0.1", "localhost"}
    assert url.database == "mediaengine_offer_classification_test"

    async def scenario() -> None:
        engine = create_async_engine(url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory.begin() as session:
                await PostgresMarketplaceIntegrationRepository(session).save(
                    _integration()
                )
                await PostgresCatalogSourceRuleRepository(session).save(_rule())
                await PostgresOfferRepository(session).save(_classified_offer("known"))

            async with factory() as session:
                stored = await PostgresOfferRepository(session).get_by_identity(
                    LEGACY_TENANT_ID,
                    "ggsel",
                    "known",
                )
                assert stored is not None
                assert stored.catalog_hub_code == "minecraft"
                assert stored.catalog_section_code == "keys"
                assert stored.catalog_source_rule_id == RULE_ID

            async with factory.begin() as session:
                await PostgresOfferRepository(session).save(
                    _unclassified_offer("known")
                )

            async with factory() as session:
                preserved = await PostgresOfferRepository(session).get_by_identity(
                    LEGACY_TENANT_ID,
                    "ggsel",
                    "known",
                )
                assert preserved is not None
                assert preserved.catalog_hub_code == "minecraft"
                assert preserved.catalog_section_code == "keys"
                assert preserved.catalog_source_rule_id == RULE_ID

            async with factory() as session:
                with pytest.raises(IntegrityError):
                    await PostgresOfferRepository(session).save(
                        _incomplete_offer("incomplete")
                    )
                    await session.commit()
                await session.rollback()

            async with factory() as session:
                await PostgresOfferRepository(session).save(
                    _classified_offer("rolled-back")
                )
                await session.rollback()

            async with factory() as session:
                repository = PostgresOfferRepository(session)
                assert (
                    await repository.get_by_identity(
                        LEGACY_TENANT_ID,
                        "ggsel",
                        "incomplete",
                    )
                    is None
                )
                assert (
                    await repository.get_by_identity(
                        LEGACY_TENANT_ID,
                        "ggsel",
                        "rolled-back",
                    )
                    is None
                )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def _integration() -> MarketplaceIntegration:
    return MarketplaceIntegration(
        id=INTEGRATION_ID,
        tenant_id=LEGACY_TENANT_ID,
        marketplace="ggsel",
        display_name="GGSEL Minecraft",
        enabled=True,
        status=MarketplaceIntegrationStatus.ACTIVE,
        source_url="https://ggsel.net/catalog/minecraft",
        created_at=NOW,
        updated_at=NOW,
    )


def _rule() -> CatalogSourceRule:
    return CatalogSourceRule(
        id=RULE_ID,
        tenant_id=LEGACY_TENANT_ID,
        integration_id=INTEGRATION_ID,
        marketplace="ggsel",
        source_category_id="minecraft-keys",
        source_category_name="Minecraft keys",
        hub_code="minecraft",
        section_code="keys",
        created_at=NOW,
        updated_at=NOW,
    )


def _classified_offer(external_id: str) -> ParsedOffer:
    return ParsedOffer(
        marketplace="ggsel",
        external_id=external_id,
        title="Minecraft key",
        url=f"https://ggsel.net/catalog/{external_id}",
        price=Decimal("790.00"),
        currency="RUB",
        source_category_id="minecraft-keys",
        source_category_name="Minecraft keys",
        catalog_hub_code="minecraft",
        catalog_section_code="keys",
        catalog_source_rule_id=RULE_ID,
    )


def _unclassified_offer(external_id: str) -> ParsedOffer:
    return ParsedOffer(
        marketplace="ggsel",
        external_id=external_id,
        title="Minecraft key updated",
        url=f"https://ggsel.net/catalog/{external_id}",
        price=Decimal("780.00"),
        currency="RUB",
        source_category_id="minecraft-keys",
    )


def _incomplete_offer(external_id: str) -> ParsedOffer:
    return ParsedOffer(
        marketplace="ggsel",
        external_id=external_id,
        title="Incomplete classification",
        url=f"https://ggsel.net/catalog/{external_id}",
        price=Decimal("700.00"),
        currency="RUB",
        catalog_hub_code="minecraft",
    )
