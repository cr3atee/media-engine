from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import uuid4

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


async def main() -> None:
    """Create a PostgreSQL RepositoryProvider and verify repository operations."""
    from app.database.session import SessionLocal, engine
    from app.domain.price_snapshot import PriceSnapshot
    from app.models.canonical_product import CanonicalProduct
    from app.parsers.models import ParsedOffer
    from app.repositories.postgres import (
        PostgresCanonicalProductRepository,
        PostgresOfferRepository,
        PostgresPriceHistoryRepository,
    )
    from app.repositories.provider import create_repository_provider

    product = CanonicalProduct(
        id=uuid4(),
        name="Minecraft Premium",
        category="games",
        aliases=("minecraft", "mc premium"),
    )
    offer = ParsedOffer(
        marketplace="ggsel",
        external_id="minecraft-premium",
        title="Minecraft Premium",
        url="https://example.com/ggsel/minecraft",
        price=Decimal("790.00"),
        currency="RUB",
        seller_id="seller-1",
        seller_name="Demo Seller",
        canonical_product_id=product.id,
    )
    snapshot = PriceSnapshot(
        marketplace="ggsel",
        external_id="minecraft-premium",
        price=Decimal("790.00"),
        currency="RUB",
        collected_at=datetime.now(UTC),
    )

    try:
        async with SessionLocal() as session:
            provider = create_repository_provider("postgres", session)
            canonical_products = cast(
                PostgresCanonicalProductRepository,
                provider.canonical_products,
            )
            offers = cast(PostgresOfferRepository, provider.offers)
            price_history = cast(
                PostgresPriceHistoryRepository,
                provider.price_history,
            )

            await canonical_products.save(product)
            await offers.save(offer)
            await price_history.add(snapshot)
            await session.commit()

            stored_products = await canonical_products.list_all()
            stored_offers = await offers.list_all()
            stored_history = await price_history.get_history(
                "ggsel",
                "minecraft-premium",
            )

        print("RepositoryProvider backend: postgres")
        print(f"Canonical repository: {type(provider.canonical_products).__name__}")
        print(f"Offer repository: {type(provider.offers).__name__}")
        print(f"Price history repository: {type(provider.price_history).__name__}")
        print(f"Stored canonical products: {stored_products}")
        print(f"Stored offers: {stored_offers}")
        print(f"Stored price history: {stored_history}")
    except Exception as exc:
        print("PostgreSQL RepositoryProvider demo failed")
        print(f"Reason: {exc}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
