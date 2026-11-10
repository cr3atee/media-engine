"""PostgreSQL verification for marketplace source category evidence."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domain.marketplace_integrations import (
    MarketplaceIntegration,
    MarketplaceIntegrationStatus,
)
from app.domain.tenancy import LEGACY_TENANT_ID
from app.parsers.models import ParsedOffer
from app.repositories.offers import OfferObservationContext
from app.repositories.postgres.postgres_marketplace_integrations import (
    PostgresMarketplaceIntegrationRepository,
)
from app.repositories.postgres.postgres_offers import PostgresOfferRepository

DATABASE_URL = os.getenv("OFFER_SOURCE_CATEGORY_TEST_DATABASE_URL")


def test_offer_source_category_persistence_and_rollback() -> None:
    """Source category evidence survives restart and transactional rollback."""
    if not DATABASE_URL:
        pytest.skip("Requires OFFER_SOURCE_CATEGORY_TEST_DATABASE_URL")
    url = make_url(DATABASE_URL)
    assert url.drivername == "postgresql+asyncpg"
    assert url.host in {"127.0.0.1", "localhost"}
    assert url.database == "mediaengine_source_category_test"

    async def scenario() -> None:
        engine = create_async_engine(url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            offer = _offer("source-category-roundtrip")
            async with factory() as session:
                await PostgresOfferRepository(session).save(offer)
                await session.commit()

            async with factory() as session:
                stored = await PostgresOfferRepository(session).get_by_identity(
                    offer.tenant_id,
                    offer.marketplace,
                    offer.external_id or "",
                )
                assert stored is not None
                assert stored.source_category_id == "28831"
                assert stored.source_category_name == "Digital keys"

            async with factory() as session:
                await PostgresOfferRepository(session).save(
                    _offer(
                        "source-category-roundtrip",
                        source_category_id=None,
                        source_category_name=None,
                    )
                )
                await session.commit()

            async with factory() as session:
                preserved = await PostgresOfferRepository(session).get_by_identity(
                    offer.tenant_id,
                    offer.marketplace,
                    offer.external_id or "",
                )
                assert preserved is not None
                assert preserved.source_category_id == "28831"
                assert preserved.source_category_name == "Digital keys"

            rollback_offer = _offer("source-category-rollback")
            async with factory() as session:
                await PostgresOfferRepository(session).save(rollback_offer)
                await session.rollback()

            async with factory() as session:
                missing = await PostgresOfferRepository(session).get_by_identity(
                    rollback_offer.tenant_id,
                    rollback_offer.marketplace,
                    rollback_offer.external_id or "",
                )
                assert missing is None
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_offer_source_categories_are_isolated_by_exact_integration() -> None:
    """Integration observations remain isolated across restart and rollback."""
    if not DATABASE_URL:
        pytest.skip("Requires OFFER_SOURCE_CATEGORY_TEST_DATABASE_URL")
    url = make_url(DATABASE_URL)
    assert url.drivername == "postgresql+asyncpg"
    assert url.host in {"127.0.0.1", "localhost"}
    assert url.database == "mediaengine_source_category_test"

    async def scenario() -> None:
        engine = create_async_engine(url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        observed_at = datetime.now(UTC)
        integration_a = _integration(uuid4(), "primary", observed_at)
        integration_b = _integration(uuid4(), "secondary", observed_at)
        offer_a = _offer(
            f"integration-a-{uuid4()}",
            source_category_id="66568",
            source_category_name=None,
        )
        offer_b = _offer(
            f"integration-b-{uuid4()}",
            source_category_id="other-category",
            source_category_name="Other category",
        )
        rollback_offer = _offer(f"rollback-{uuid4()}")
        try:
            async with factory() as session:
                integrations = PostgresMarketplaceIntegrationRepository(session)
                offers = PostgresOfferRepository(session)
                await integrations.save(integration_a)
                await integrations.save(integration_b)
                await offers.save_observed(
                    _observation(integration_a.id, observed_at),
                    offer_a,
                )
                await offers.save_observed(
                    _observation(integration_b.id, observed_at),
                    offer_b,
                )
                await session.commit()

            async with factory() as session:
                offers = PostgresOfferRepository(session)
                primary = tuple(
                    await offers.list_by_integration(
                        LEGACY_TENANT_ID,
                        integration_a.id,
                    )
                )
                secondary = tuple(
                    await offers.list_by_integration(
                        LEGACY_TENANT_ID,
                        integration_b.id,
                    )
                )
                foreign = tuple(
                    await offers.list_by_integration(UUID(int=999), integration_a.id)
                )
                assert tuple(offer.external_id for offer in primary) == (
                    offer_a.external_id,
                )
                assert tuple(offer.external_id for offer in secondary) == (
                    offer_b.external_id,
                )
                assert foreign == ()

            async with factory() as session:
                offers = PostgresOfferRepository(session)
                deactivated = await offers.reconcile_observations(
                    _observation(
                        integration_a.id,
                        observed_at + timedelta(minutes=1),
                    ),
                    {"different-offer"},
                )
                assert deactivated == 1
                await session.commit()

            async with factory() as session:
                offers = PostgresOfferRepository(session)
                assert (
                    tuple(
                        await offers.list_by_integration(
                            LEGACY_TENANT_ID,
                            integration_a.id,
                        )
                    )
                    == ()
                )
                assert tuple(
                    offer.external_id
                    for offer in await offers.list_by_integration(
                        LEGACY_TENANT_ID,
                        integration_b.id,
                    )
                ) == (offer_b.external_id,)

            async with factory() as session:
                await PostgresOfferRepository(session).save_observed(
                    _observation(integration_a.id, observed_at + timedelta(minutes=2)),
                    rollback_offer,
                )
                await session.rollback()

            async with factory() as session:
                assert (
                    await PostgresOfferRepository(session).get_by_identity(
                        LEGACY_TENANT_ID,
                        rollback_offer.marketplace,
                        rollback_offer.external_id or "",
                    )
                    is None
                )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def _offer(
    external_id: str,
    *,
    source_category_id: str | None = "28831",
    source_category_name: str | None = "Digital keys",
) -> ParsedOffer:
    return ParsedOffer(
        marketplace="ggsel",
        external_id=external_id,
        title="Minecraft Java & Bedrock Edition",
        url=f"https://ggsel.net/catalog/{external_id}",
        price=Decimal("790.00"),
        currency="RUB",
        seller_id="seller-1",
        seller_name="Seller",
        source_category_id=source_category_id,
        source_category_name=source_category_name,
    )


def _integration(
    integration_id: UUID,
    account: str,
    timestamp: datetime,
) -> MarketplaceIntegration:
    return MarketplaceIntegration(
        id=integration_id,
        tenant_id=LEGACY_TENANT_ID,
        marketplace="ggsel",
        display_name=f"GGSEL {account}",
        enabled=True,
        status=MarketplaceIntegrationStatus.ACTIVE,
        external_account_id=f"{account}-{integration_id}",
        source_url=f"https://ggsel.net/catalog/{account}-{integration_id}",
        created_at=timestamp,
        updated_at=timestamp,
    )


def _observation(
    integration_id: UUID,
    observed_at: datetime,
) -> OfferObservationContext:
    return OfferObservationContext(
        tenant_id=LEGACY_TENANT_ID,
        integration_id=integration_id,
        marketplace="ggsel",
        observed_at=observed_at,
    )
