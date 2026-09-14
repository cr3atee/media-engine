# ruff: noqa: E402

from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.domain.lifecycle import ScoringStatus
from app.domain.market_events import (
    MarketEventCandidate,
    PriceDropMarketEvent,
    PriceDropPayload,
    SnapshotIdentity,
    create_price_drop_market_event,
)
from app.domain.price_snapshot import PriceSnapshot
from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer
from app.repositories.provider import create_memory_provider
from app.repositories.public_queries.models import (
    PublicCategoryQuery,
    PublicOfferQuery,
    PublicPriceChangeQuery,
    PublicPriceHistoryQuery,
    PublicProductQuery,
)
from app.repositories.public_queries.repository_backed import (
    RepositoryBackedPublicReadRepository,
)
from app.repositories.queries.models import PageRequest

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


async def main() -> None:
    """Demonstrate public Market Terminal reads over the memory provider."""
    provider = create_memory_provider()
    product = CanonicalProduct(
        id=UUID(int=1),
        name="Minecraft Premium",
        category="Games",
        aliases=("minecraft", "mc"),
    )
    await provider.canonical_products.save(product)

    playerok = ParsedOffer(
        marketplace="playerok",
        external_id="playerok-1",
        title="Minecraft Premium",
        url="https://example.com/playerok",
        price=Decimal("790.00"),
        currency="RUB",
        seller_name="Playerok Seller",
        canonical_product_id=product.id,
    )
    ggsel = ParsedOffer(
        marketplace="ggsel",
        external_id="ggsel-1",
        title="Minecraft Premium",
        url="https://example.com/ggsel",
        price=Decimal("990.00"),
        currency="RUB",
        seller_name="GGSEL Seller",
        canonical_product_id=product.id,
    )
    await provider.offers.save(playerok)
    await provider.offers.save(ggsel)
    await provider.price_history.add(
        PriceSnapshot(
            marketplace="playerok",
            external_id="playerok-1",
            price=Decimal("990.00"),
            currency="RUB",
            collected_at=NOW - timedelta(hours=1),
        ),
    )
    await provider.price_history.add(
        PriceSnapshot(
            marketplace="playerok",
            external_id="playerok-1",
            price=Decimal("790.00"),
            currency="RUB",
            collected_at=NOW,
        ),
    )
    await provider.events.add_idempotently(
        MarketEventCandidate(event=_price_drop_event(product.id)),
    )

    repository = RepositoryBackedPublicReadRepository(provider)
    products = await repository.list_products(
        PublicProductQuery(search="minecraft"),
        _page(sort="recently_updated", direction="desc"),
    )
    offers = await repository.list_offers(
        PublicOfferQuery(product_id=product.id),
        _page(sort="price", direction="asc"),
    )
    comparison = await repository.get_comparison(product.id)
    history = await repository.list_price_history(
        PublicPriceHistoryQuery(product_id=product.id, marketplace="playerok"),
        _page(sort="collected_at", direction="asc"),
    )
    changes = await repository.list_price_changes(
        PublicPriceChangeQuery(product_id=product.id),
        _page(sort="changed_at", direction="desc"),
    )
    categories = await repository.list_categories(
        PublicCategoryQuery(),
        _page(sort="name", direction="asc"),
    )

    print("=== PRODUCTS ===")
    print(products.items)
    print("=== OFFERS ===")
    print(offers.items)
    print("=== COMPARISON ===")
    print(comparison)
    print("=== PRICE HISTORY ===")
    print(history.items)
    print("=== PRICE CHANGES ===")
    print(changes.items)
    print("=== CATEGORIES ===")
    print(categories.items)


def _price_drop_event(product_id: UUID) -> PriceDropMarketEvent:
    previous = SnapshotIdentity(
        marketplace="playerok",
        external_id="playerok-1",
        collected_at=NOW - timedelta(hours=1),
        price=Decimal("990.00"),
        currency="RUB",
    )
    current = SnapshotIdentity(
        marketplace="playerok",
        external_id="playerok-1",
        collected_at=NOW,
        price=Decimal("790.00"),
        currency="RUB",
    )
    event = create_price_drop_market_event(
        payload=PriceDropPayload(
            title="Minecraft Premium",
            url="https://example.com/playerok",
            old_price=previous.price,
            new_price=current.price,
            currency="RUB",
            absolute_difference=Decimal("200.00"),
            percentage=Decimal("20.202020"),
            previous_snapshot=previous,
            current_snapshot=current,
        ),
        detected_at=NOW + timedelta(seconds=1),
        canonical_product_id=product_id,
        created_at=NOW + timedelta(seconds=2),
    )
    return replace(
        event,
        scoring_status=ScoringStatus.SUCCEEDED,
        score=80,
    )


def _page(*, sort: str, direction: str) -> PageRequest:
    return PageRequest(
        limit=10,
        sort=sort,
        direction=direction,
        filter_hash="demo",
    )


if __name__ == "__main__":
    asyncio.run(main())
