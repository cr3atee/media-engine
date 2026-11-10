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
    PublicCatalogHubQuery,
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


def test_product_marketplace_identities_are_sorted_unique_and_product_scoped() -> None:
    asyncio.run(_assert_marketplace_identities())


def test_public_categories_use_fixed_taxonomy_and_legacy_values() -> None:
    asyncio.run(_assert_fixed_category_taxonomy())


def test_public_catalog_hubs_use_only_consistent_verified_classification() -> None:
    asyncio.run(_assert_verified_catalog_hubs())


async def _assert_verified_catalog_hubs() -> None:
    provider = create_memory_provider()
    products = (
        CanonicalProduct(
            id=UUID(int=201),
            name="Minecraft Java & Bedrock",
            category="Games",
            aliases=(),
        ),
        CanonicalProduct(
            id=UUID(int=202),
            name="Fortnite account",
            category="Accounts",
            aliases=(),
        ),
        CanonicalProduct(
            id=UUID(int=203),
            name="Unknown product",
            category=None,
            aliases=(),
        ),
        CanonicalProduct(
            id=UUID(int=204),
            name="Conflicting product",
            category=None,
            aliases=(),
        ),
        CanonicalProduct(
            id=UUID(int=205),
            name="Incomplete classification",
            category=None,
            aliases=(),
        ),
    )
    for product in products:
        await provider.canonical_products.save(product)

    offers = (
        _classified_offer(201, "ggsel", "minecraft", "keys", 301),
        _classified_offer(201, "playerok", "minecraft", "keys", 302),
        _classified_offer(202, "playerok", "fortnite", "accounts", 303),
        ParsedOffer(
            marketplace="funpay",
            external_id="unknown",
            title="Unknown product",
            url=None,
            price=Decimal("100"),
            currency="RUB",
            canonical_product_id=products[2].id,
        ),
        _classified_offer(204, "ggsel", "minecraft", "keys", 304),
        _classified_offer(204, "playerok", "fortnite", "accounts", 305),
        ParsedOffer(
            marketplace="ggsel",
            external_id="incomplete",
            title="Incomplete classification",
            url=None,
            price=Decimal("100"),
            currency="RUB",
            catalog_hub_code="minecraft",
            catalog_section_code="keys",
            canonical_product_id=products[4].id,
        ),
    )
    for offer in offers:
        await provider.offers.save(offer)

    repository = RepositoryBackedPublicReadRepository(provider)
    hubs = await repository.list_catalog_hubs(
        PublicCatalogHubQuery(),
        _page(sort="product_count", direction="desc"),
    )

    assert [hub.code for hub in hubs.items] == ["minecraft", "fortnite"]
    minecraft = hubs.items[0]
    assert minecraft.product_count == 1
    assert minecraft.offer_count == 2
    assert minecraft.marketplaces == ("ggsel", "playerok")
    assert len(minecraft.sections) == 1
    assert minecraft.sections[0].code == "keys"
    assert minecraft.sections[0].product_count == 1
    assert minecraft.sections[0].offer_count == 2

    filtered_products = await repository.list_products(
        PublicProductQuery(hub="minecraft", section="keys"),
        _page(sort="name", direction="asc"),
    )
    assert [item.id for item in filtered_products.items] == [UUID(int=201)]
    assert filtered_products.items[0].catalog_hub_code == "minecraft"
    assert filtered_products.items[0].catalog_section_code == "keys"

    ggsel_hubs = await repository.list_catalog_hubs(
        PublicCatalogHubQuery(marketplace="ggsel"),
        _page(sort="code", direction="asc"),
    )
    assert len(ggsel_hubs.items) == 1
    assert ggsel_hubs.items[0].code == "minecraft"
    assert ggsel_hubs.items[0].offer_count == 1
    assert ggsel_hubs.items[0].marketplaces == ("ggsel",)


def _classified_offer(
    product_number: int,
    marketplace: str,
    hub_code: str,
    section_code: str,
    rule_number: int,
) -> ParsedOffer:
    return ParsedOffer(
        marketplace=marketplace,
        external_id=f"{marketplace}-{product_number}",
        title=f"Product {product_number}",
        url=f"https://example.com/{marketplace}/{product_number}",
        price=Decimal("790"),
        currency="RUB",
        catalog_hub_code=hub_code,
        catalog_section_code=section_code,
        catalog_source_rule_id=UUID(int=rule_number),
        canonical_product_id=UUID(int=product_number),
    )


async def _assert_fixed_category_taxonomy() -> None:
    provider = create_memory_provider()
    product = CanonicalProduct(
        id=UUID(int=101),
        name="Minecraft",
        category="Games",
        aliases=(),
    )
    await provider.canonical_products.save(product)
    await provider.offers.save(
        ParsedOffer(
            marketplace="ggsel",
            external_id="category-offer",
            title="Minecraft key",
            url="https://example.com/category-offer",
            price=Decimal("500"),
            currency="RUB",
            canonical_product_id=product.id,
        )
    )
    repository = RepositoryBackedPublicReadRepository(provider)

    categories = await repository.list_categories(
        PublicCategoryQuery(),
        _page(sort="name", direction="asc"),
    )
    products = await repository.list_products(
        PublicProductQuery(category="Игры и предметы"),
        _page(sort="name", direction="asc"),
    )

    counts = {item.code: item.product_count for item in categories.items}
    assert set(counts) == {"games", "keys", "accounts", "subscriptions", "topups"}
    assert counts["games"] == 1
    assert sum(counts.values()) == 1
    assert len(products.items) == 1
    assert products.items[0].category == "Игры и предметы"


async def _assert_marketplace_identities() -> None:
    provider = create_memory_provider()
    product = CanonicalProduct(
        id=UUID(int=1), name="Minecraft", category=None, aliases=()
    )
    empty_product = replace(product, id=UUID(int=2), name="Empty product")
    await provider.canonical_products.save(product)
    await provider.canonical_products.save(empty_product)
    for index, marketplace in enumerate(("playerok", "ggsel", "ggsel")):
        await provider.offers.save(
            ParsedOffer(
                marketplace=marketplace,
                external_id=str(index),
                title="Minecraft",
                url=None,
                price=Decimal("790"),
                currency="RUB",
                canonical_product_id=product.id,
            )
        )
    await provider.offers.save(
        ParsedOffer(
            marketplace="funpay",
            external_id="unlinked",
            title="Unlinked offer",
            url=None,
            price=None,
            currency=None,
        )
    )
    repository = RepositoryBackedPublicReadRepository(provider)
    page = await repository.list_products(
        PublicProductQuery(marketplace="ggsel"), _page(sort="name", direction="asc")
    )
    assert len(page.items) == 1
    assert page.items[0].marketplaces == ("ggsel", "playerok")
    assert page.items[0].marketplace_count == 2
    assert page.items[0].offer_count == 3
    detail = await repository.get_product(product.id)
    assert detail is not None
    assert detail.marketplaces == page.items[0].marketplaces
    empty = await repository.get_product(empty_product.id)
    assert empty is not None
    assert empty.marketplaces == ()
    assert empty.marketplace_count == 0


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
    assert products.items[0].marketplaces == ("ggsel", "playerok")
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
