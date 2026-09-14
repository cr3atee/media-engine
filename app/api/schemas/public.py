from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import AliasChoices, Field, field_validator, model_validator

from app.api.schemas.common import ApiModel, utc_datetime
from app.comparator.result import ComparisonStatus

ProductSort = Literal[
    "name",
    "price_asc",
    "price_desc",
    "popular",
    "recently_updated",
]
PriceHistoryPeriod = Literal["7d", "30d", "90d", "1y", "all"]
OfferSort = Literal["price", "marketplace", "title"]
PriceHistorySort = Literal["collected_at"]
PriceChangeSort = Literal["changed_at"]
CategorySort = Literal["name", "product_count"]
SortDirection = Literal["asc", "desc"]


def _optional_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return utc_datetime(value)


def _required_utc_datetime(value: datetime) -> datetime:
    return utc_datetime(value)


def _validate_decimal_range(
    start: Decimal | None,
    end: Decimal | None,
    name: str,
) -> None:
    if start is not None and end is not None and start > end:
        raise ValueError(f"{name} range start must not be after its end.")


def _validate_datetime_range(
    start: datetime | None,
    end: datetime | None,
    name: str,
) -> None:
    if start is not None and end is not None and start > end:
        raise ValueError(f"{name} range start must not be after its end.")


class PublicProductsQueryParams(ApiModel):
    """Validated filters for public product browsing and search."""

    search: str | None = Field(
        default=None,
        max_length=200,
        validation_alias=AliasChoices("search", "q"),
    )
    category: str | None = Field(default=None, max_length=120)
    marketplace: str | None = Field(default=None, max_length=64)
    min_price: Decimal | None = Field(default=None, ge=0)
    max_price: Decimal | None = Field(default=None, ge=0)
    sort: ProductSort = "recently_updated"
    direction: SortDirection = "desc"
    limit: int | None = Field(default=None, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def validate_price_range(self) -> PublicProductsQueryParams:
        """Reject reversed explicit price ranges."""
        _validate_decimal_range(self.min_price, self.max_price, "price")
        return self


class PublicOffersQueryParams(ApiModel):
    """Validated filters for public product marketplace offers."""

    marketplace: str | None = Field(default=None, max_length=64)
    min_price: Decimal | None = Field(default=None, ge=0)
    max_price: Decimal | None = Field(default=None, ge=0)
    sort: OfferSort = "price"
    direction: SortDirection = "asc"
    limit: int | None = Field(default=None, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def validate_price_range(self) -> PublicOffersQueryParams:
        """Reject reversed explicit price ranges."""
        _validate_decimal_range(self.min_price, self.max_price, "price")
        return self


class PublicPriceHistoryQueryParams(ApiModel):
    """Validated filters for public product price-history charts."""

    period: PriceHistoryPeriod = "30d"
    marketplace: str | None = Field(default=None, max_length=64)
    sort: PriceHistorySort = "collected_at"
    direction: SortDirection = "asc"
    limit: int | None = Field(default=None, ge=1, le=1000)
    cursor: str | None = Field(default=None, max_length=2048)


class PublicPriceChangesQueryParams(ApiModel):
    """Validated filters for public latest price-change feeds."""

    marketplace: str | None = Field(default=None, max_length=64)
    product_id: UUID | None = None
    changed_from: datetime | None = None
    changed_to: datetime | None = None
    sort: PriceChangeSort = "changed_at"
    direction: SortDirection = "desc"
    limit: int | None = Field(default=None, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=2048)

    _normalize_changed_from = field_validator("changed_from")(_optional_utc_datetime)
    _normalize_changed_to = field_validator("changed_to")(_optional_utc_datetime)

    @model_validator(mode="after")
    def validate_changed_range(self) -> PublicPriceChangesQueryParams:
        """Reject reversed explicit changed-at windows."""
        _validate_datetime_range(self.changed_from, self.changed_to, "changed")
        return self


class PublicCategoriesQueryParams(ApiModel):
    """Validated filters for public category browse lists."""

    search: str | None = Field(
        default=None,
        max_length=120,
        validation_alias=AliasChoices("search", "q"),
    )
    sort: CategorySort = "name"
    direction: SortDirection = "asc"
    limit: int | None = Field(default=None, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=2048)


class PublicOfferSummary(ApiModel):
    """UI-safe marketplace offer summary."""

    marketplace: str
    external_id: str | None
    title: str | None
    url: str | None
    price: Decimal | None = Field(default=None, ge=0)
    currency: str | None
    seller_id: str | None = None
    seller_name: str | None = None


class PublicProductCard(ApiModel):
    """Compact product card for home, search, and category views."""

    id: UUID
    name: str
    category: str | None
    best_offer: PublicOfferSummary | None
    offer_count: int = Field(ge=0)
    marketplace_count: int = Field(ge=0)
    updated_at: datetime | None = None

    _normalize_updated_at = field_validator("updated_at")(_optional_utc_datetime)


class PublicProductDetail(ApiModel):
    """Product detail payload for the public product page."""

    id: UUID
    name: str
    category: str | None
    aliases: list[str]
    best_offer: PublicOfferSummary | None
    offer_count: int = Field(ge=0)
    marketplace_count: int = Field(ge=0)
    updated_at: datetime | None = None

    _normalize_updated_at = field_validator("updated_at")(_optional_utc_datetime)


class PublicPriceDifference(ApiModel):
    """Difference between one offer and the selected best offer."""

    offer: PublicOfferSummary
    absolute_difference: Decimal | None = Field(default=None, ge=0)
    percentage_difference: Decimal | None = Field(default=None, ge=0)
    reason: str | None = None


class PublicComparisonResult(ApiModel):
    """UI-safe comparison result for one product."""

    product: PublicProductDetail | None
    offers: list[PublicOfferSummary]
    best_offer: PublicOfferSummary | None
    differences: list[PublicPriceDifference]
    status: ComparisonStatus


class PublicPriceHistoryPoint(ApiModel):
    """One public chart point for a product price history."""

    marketplace: str
    price: Decimal = Field(ge=0)
    currency: str
    collected_at: datetime

    _normalize_collected_at = field_validator("collected_at")(_required_utc_datetime)


class PublicPriceChange(ApiModel):
    """Public latest price-change entry for feeds and product pages."""

    product_id: UUID | None
    product_name: str
    marketplace: str
    old_price: Decimal = Field(ge=0)
    new_price: Decimal = Field(ge=0)
    currency: str
    discount_percent: Decimal = Field(ge=0)
    changed_at: datetime
    url: str | None = None

    _normalize_changed_at = field_validator("changed_at")(_required_utc_datetime)


class PublicCategory(ApiModel):
    """Public product category summary."""

    code: str
    name: str
    product_count: int = Field(ge=0)
