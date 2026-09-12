from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from app.repositories.public_queries import (
    CategoryRead,
    OfferSummaryRead,
    PriceChangeRead,
    PriceDifferenceRead,
    PriceHistoryPointRead,
    ProductComparisonRead,
    ProductDetailRead,
    ProductSummaryRead,
    PublicCategoryQuery,
    PublicCategoryQueryRepository,
    PublicComparisonQueryRepository,
    PublicOfferQuery,
    PublicOfferQueryRepository,
    PublicPriceChangeQuery,
    PublicPriceChangeQueryRepository,
    PublicPriceHistoryQuery,
    PublicPriceHistoryQueryRepository,
    PublicProductQuery,
    PublicProductQueryRepository,
)


def _offer() -> OfferSummaryRead:
    return OfferSummaryRead(
        marketplace="playerok",
        external_id="offer-1",
        title="Minecraft Premium",
        url="https://example.com/product",
        price=Decimal("790.00"),
        currency="RUB",
        seller_id="seller-1",
        seller_name="Seller",
        canonical_product_id=UUID(int=1),
    )


def test_public_query_models_are_immutable_and_decimal_safe() -> None:
    offer = _offer()
    product = ProductSummaryRead(
        id=UUID(int=1),
        name="Minecraft Premium",
        category="games",
        best_offer=offer,
        offer_count=2,
        marketplace_count=2,
        updated_at=datetime(2026, 9, 12, 12, 0, tzinfo=UTC),
    )

    assert product.best_offer is offer
    assert product.best_offer.price == Decimal("790.00")
    field_name = "name"
    with pytest.raises(FrozenInstanceError):
        setattr(product, field_name, "Changed")


def test_public_query_objects_cover_consumer_filters() -> None:
    product_query = PublicProductQuery(
        tenant_id=UUID(int=10),
        search="minecraft",
        category="games",
        marketplace="ggsel",
        min_price=Decimal("100"),
        max_price=Decimal("900"),
    )
    offer_query = PublicOfferQuery(product_id=UUID(int=1), marketplace="playerok")
    history_query = PublicPriceHistoryQuery(
        product_id=UUID(int=1),
        collected_from=datetime(2026, 9, 12, 0, 0, tzinfo=UTC),
    )
    change_query = PublicPriceChangeQuery(
        product_id=UUID(int=1),
        changed_to=datetime(2026, 9, 12, 12, 0, tzinfo=UTC),
    )
    category_query = PublicCategoryQuery(search="game")

    assert product_query.search == "minecraft"
    assert offer_query.marketplace == "playerok"
    assert history_query.product_id == UUID(int=1)
    assert change_query.changed_to == datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    assert category_query.search == "game"


def test_public_read_projections_cover_market_terminal_views() -> None:
    offer = _offer()
    product = ProductDetailRead(
        id=UUID(int=1),
        name="Minecraft Premium",
        category="games",
        aliases=("minecraft",),
        best_offer=offer,
        offer_count=2,
        marketplace_count=2,
        updated_at=None,
    )
    comparison = ProductComparisonRead(
        product=product,
        offers=(offer,),
        best_offer=offer,
        differences=(
            PriceDifferenceRead(
                offer=offer,
                absolute_difference=Decimal("0"),
                percentage_difference=Decimal("0"),
                reason=None,
            ),
        ),
        status="complete",
    )
    history_point = PriceHistoryPointRead(
        marketplace="playerok",
        price=Decimal("790.00"),
        currency="RUB",
        collected_at=datetime(2026, 9, 12, 12, 0, tzinfo=UTC),
    )
    price_change = PriceChangeRead(
        product_id=UUID(int=1),
        product_name="Minecraft Premium",
        marketplace="playerok",
        old_price=Decimal("990.00"),
        new_price=Decimal("790.00"),
        currency="RUB",
        discount_percent=Decimal("20.20"),
        changed_at=history_point.collected_at,
        url=offer.url,
    )
    category = CategoryRead(code="games", name="Games", product_count=1)

    assert comparison.product is product
    assert comparison.best_offer is offer
    assert history_point.price == Decimal("790.00")
    assert price_change.discount_percent == Decimal("20.20")
    assert category.product_count == 1


def test_public_repository_contracts_define_expected_methods() -> None:
    expected = {
        PublicProductQueryRepository: {"list_products", "get_product"},
        PublicOfferQueryRepository: {"list_offers"},
        PublicComparisonQueryRepository: {"get_comparison"},
        PublicPriceHistoryQueryRepository: {"list_price_history"},
        PublicPriceChangeQueryRepository: {"list_price_changes"},
        PublicCategoryQueryRepository: {"list_categories"},
    }

    for repository, methods in expected.items():
        assert repository.__abstractmethods__ == methods


def test_public_query_contract_layer_has_no_transport_or_orm_dependencies() -> None:
    paths = (
        Path("app/repositories/public_queries/contracts.py"),
        Path("app/repositories/public_queries/models.py"),
    )
    forbidden = (
        "sqlalchemy",
        "app.api",
        "app.database",
        "app.telegram",
        "app.adapters.telegram",
    )

    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        imports.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        assert not any(
            module.startswith(prefix) for module in imports for prefix in forbidden
        ), path
