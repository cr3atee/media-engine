"""PostgreSQL verification for marketplace source category evidence."""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.parsers.models import ParsedOffer
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
