from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

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
from app.repositories.queries.models import CursorPosition, PageRequest

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


def test_repository_backed_public_reads_project_market_terminal_data() -> None:
    asyncio.run(_assert_repository_backed_public_reads())


@pytest.mark.parametrize(
    ("sort", "direction"),
    [
        ("recently_updated", "desc"),
        ("name", "asc"),
        ("name", "desc"),
        ("price_asc", "asc"),
        ("price_desc", "desc"),
        ("popular", "desc"),
    ],
)
def test_product_pages_follow_every_supported_sort_without_overlap(
    sort: str,
    direction: str,
) -> None:
    asyncio.run(_assert_product_pages(sort=sort, direction=direction))


def test_missing_product_cursor_anchor_ends_pagination_safely() -> None:
    asyncio.run(_assert_missing_product_cursor_anchor())


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


async def _assert_product_pages(*, sort: str, direction: str) -> None:
    repository = await _pagination_repository()
    expected = await repository.list_products(
        PublicProductQuery(),
        _page(sort=sort, direction=direction, limit=100),
    )

    seen_ids: list[UUID] = []
    cursor: CursorPosition | None = None
    for _ in range(10):
        result = await repository.list_products(
            PublicProductQuery(),
            _page(
                sort=sort,
                direction=direction,
                limit=2,
                cursor=cursor,
            ),
        )
        seen_ids.extend(item.id for item in result.items)
        cursor = result.next_cursor
        if cursor is None:
            break
        assert cursor.resource == "public_products"
        assert cursor.sort == sort
        assert cursor.direction == direction
        assert cursor.filter_hash == "test"
        assert cursor.timestamp.tzinfo is not None
    else:
        pytest.fail("Product pagination did not terminate.")

    expected_ids = [item.id for item in expected.items]
    assert seen_ids == expected_ids
    assert len(seen_ids) == len(set(seen_ids))


async def _assert_missing_product_cursor_anchor() -> None:
    repository = await _pagination_repository()
    result = await repository.list_products(
        PublicProductQuery(),
        _page(
            sort="name",
            direction="asc",
            limit=2,
            cursor=CursorPosition(
                resource="public_products",
                sort="name",
                direction="asc",
                timestamp=NOW,
                item_id=UUID(int=999),
                filter_hash="test",
            ),
        ),
    )

    assert result.items == ()
    assert result.next_cursor is None


async def _pagination_repository() -> RepositoryBackedPublicReadRepository:
    provider = create_memory_provider()
    products = (
        (1, "Alpha", Decimal("500.00")),
        (2, "Bravo", Decimal("300.00")),
        (3, "Charlie", Decimal("900.00")),
        (4, "Delta", Decimal("100.00")),
        (5, "Echo", Decimal("700.00")),
    )
    for product_id, name, price in products:
        product = CanonicalProduct(
            id=UUID(int=product_id),
            name=name,
            category="Games",
            aliases=(),
        )
        await provider.canonical_products.save(product)
        await provider.offers.save(
            ParsedOffer(
                marketplace="ggsel",
                external_id=f"ggsel-{product_id}",
                title=name,
                url=f"https://example.com/{product_id}",
                price=price,
                currency="RUB",
                canonical_product_id=product.id,
            ),
        )
    return RepositoryBackedPublicReadRepository(provider)


def _page(
    *,
    sort: str,
    direction: str,
    limit: int = 10,
    cursor: CursorPosition | None = None,
) -> PageRequest:
    return PageRequest(
        limit=limit,
        sort=sort,
        direction=direction,
        filter_hash="test",
        cursor=cursor,
    )
