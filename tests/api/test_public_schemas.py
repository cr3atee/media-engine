from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.api.schemas.public import (
    PublicCategory,
    PublicComparisonResult,
    PublicOfferSummary,
    PublicPriceChange,
    PublicPriceChangesQueryParams,
    PublicPriceDifference,
    PublicPriceHistoryPoint,
    PublicProductCard,
    PublicProductDetail,
    PublicProductsQueryParams,
)
from app.comparator.result import ComparisonStatus


def _offer(price: Decimal = Decimal("790.00")) -> PublicOfferSummary:
    return PublicOfferSummary(
        marketplace="playerok",
        external_id="offer-1",
        title="Minecraft Premium",
        url="https://example.com/product",
        price=price,
        currency="RUB",
        seller_id="seller-1",
        seller_name="Seller",
    )


def test_public_product_card_is_ui_safe_and_decimal_precise() -> None:
    updated_at = datetime(2026, 9, 11, 12, 0, tzinfo=timezone(timedelta(hours=7)))

    card = PublicProductCard(
        id=UUID(int=1),
        name="Minecraft Premium",
        category="games",
        best_offer=_offer(),
        offer_count=3,
        marketplace_count=2,
        updated_at=updated_at,
    )

    payload = card.model_dump(mode="json")
    assert payload["best_offer"]["price"] == "790.00"
    assert card.updated_at == datetime(2026, 9, 11, 5, 0, tzinfo=UTC)
    assert "claim_token" not in payload


def test_public_schemas_reject_extra_fields() -> None:
    with pytest.raises(ValidationError):
        PublicOfferSummary.model_validate(
            {
                "marketplace": "ggsel",
                "external_id": "1",
                "title": "Minecraft Premium",
                "url": "https://example.com/product",
                "price": Decimal("790.00"),
                "currency": "RUB",
                "claim_token": "secret",
            }
        )


def test_product_query_params_are_bounded() -> None:
    params = PublicProductsQueryParams.model_validate(
        {
            "q": "minecraft",
            "min_price": Decimal("100"),
            "max_price": Decimal("900"),
            "limit": 20,
        }
    )

    assert params.search == "minecraft"
    assert params.sort == "recently_updated"

    with pytest.raises(ValidationError):
        PublicProductsQueryParams(min_price=Decimal("900"), max_price=Decimal("100"))

    with pytest.raises(ValidationError):
        PublicProductsQueryParams(limit=101)


def test_price_change_query_params_require_aware_ordered_dates() -> None:
    changed_from = datetime(2026, 9, 11, 12, 0, tzinfo=timezone(timedelta(hours=7)))
    changed_to = datetime(2026, 9, 11, 13, 0, tzinfo=timezone(timedelta(hours=7)))

    params = PublicPriceChangesQueryParams(
        changed_from=changed_from,
        changed_to=changed_to,
    )

    assert params.changed_from == datetime(2026, 9, 11, 5, 0, tzinfo=UTC)
    assert params.changed_to == datetime(2026, 9, 11, 6, 0, tzinfo=UTC)

    with pytest.raises(ValidationError):
        PublicPriceChangesQueryParams(
            changed_from=datetime(2026, 9, 11, 13, 0, tzinfo=UTC),
            changed_to=datetime(2026, 9, 11, 12, 0, tzinfo=UTC),
        )

    with pytest.raises(ValidationError):
        PublicPriceChangesQueryParams(
            changed_from=datetime(2026, 9, 11, 12, 0),
        )


def test_public_comparison_result_contains_only_read_dtos() -> None:
    product = PublicProductDetail(
        id=UUID(int=1),
        name="Minecraft Premium",
        category="games",
        aliases=["minecraft"],
        best_offer=_offer(),
        offer_count=2,
        marketplace_count=2,
    )
    other_offer = _offer(Decimal("990.00"))

    result = PublicComparisonResult(
        product=product,
        offers=[product.best_offer, other_offer]
        if product.best_offer
        else [other_offer],
        best_offer=product.best_offer,
        differences=[
            PublicPriceDifference(
                offer=other_offer,
                absolute_difference=Decimal("200.00"),
                percentage_difference=Decimal("25.316455"),
                reason=None,
            )
        ],
        status=ComparisonStatus.COMPLETE,
    )

    assert result.status is ComparisonStatus.COMPLETE
    assert result.differences[0].absolute_difference == Decimal("200.00")


def test_price_history_change_and_category_dtos_normalize_time() -> None:
    collected_at = datetime(2026, 9, 11, 12, 0, tzinfo=timezone(timedelta(hours=7)))

    point = PublicPriceHistoryPoint(
        marketplace="funpay",
        price=Decimal("790.00"),
        currency="RUB",
        collected_at=collected_at,
    )
    change = PublicPriceChange(
        product_id=UUID(int=1),
        product_name="Minecraft Premium",
        marketplace="funpay",
        old_price=Decimal("990.00"),
        new_price=Decimal("790.00"),
        currency="RUB",
        discount_percent=Decimal("20.20"),
        changed_at=collected_at,
        url="https://example.com/product",
    )
    category = PublicCategory(code="games", name="Games", product_count=12)

    assert point.collected_at == datetime(2026, 9, 11, 5, 0, tzinfo=UTC)
    assert change.changed_at == datetime(2026, 9, 11, 5, 0, tzinfo=UTC)
    assert category.product_count == 12
