from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from app.domain.lifecycle import ScoringStatus
from app.domain.market_events import (
    MarketEventCandidate,
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


def test_repository_backed_public_reads_project_market_terminal_data() -> None:
    asyncio.run(_assert_repository_backed_public_reads())


async def _assert_repository_backed_public_reads() -> None:
    provider = create_memory_provider()
    product = CanonicalProduct(
        id=UUID(int=1),
        name="Minecraft Premium",
        category="Games",
        aliases=("minecraft", "mc"),
    )
    await provider.canonical_products.save(product)

    first_offer = ParsedOffer(
        marketplace="playerok",
        external_id="playerok-1",
        title="Minecraft Premium",
        url="https://example.com/playerok",
        price=Decimal("790.00"),
        currency="RUB",
        seller_id="seller-1",
        seller_name="Seller One",
        canonical_product_id=product.id,
    )
    second_offer = ParsedOffer(
        marketplace="ggsel",
        external_id="ggsel-1",
        title="Minecraft Premium",
        url="https://example.com/ggsel",
        price=Decimal("990.00"),
        currency="RUB",
        seller_id="seller-2",
        seller_name="Seller Two",
        canonical_product_id=product.id,
    )
    await provider.offers.save(first_offer)
    await provider.offers.save(second_offer)
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
    event = replace(
        create_price_drop_market_event(
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
            canonical_product_id=product.id,
            created_at=NOW + timedelta(seconds=2),
        ),
        scoring_status=ScoringStatus.SUCCEEDED,
        score=80,
    )
    await provider.events.add_idempotently(MarketEventCandidate(event=event))

    repository = RepositoryBackedPublicReadRepository(provider)
    products = await repository.list_products(
        PublicProductQuery(search="mine"),
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
        PublicCategoryQuery(search="game"),
        _page(sort="name", direction="asc"),
    )

    assert products.items[0].name == "Minecraft Premium"
    assert products.items[0].best_offer is not None
    assert products.items[0].best_offer.price == Decimal("790.00")
    assert len(offers.items) == 2
    assert offers.items[0].marketplace == "playerok"
    assert comparison is not None
    assert comparison.status == "complete"
    assert comparison.best_offer is not None
    assert comparison.best_offer.marketplace == "playerok"
    assert [point.price for point in history.items] == [
        Decimal("990.00"),
        Decimal("790.00"),
    ]
    assert changes.items[0].old_price == Decimal("990.00")
    assert changes.items[0].new_price == Decimal("790.00")
    assert categories.items[0].code == "games"


def _page(*, sort: str, direction: str) -> PageRequest:
    return PageRequest(
        limit=10,
        sort=sort,
        direction=direction,
        filter_hash="test",
    )
