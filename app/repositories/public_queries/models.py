from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass(slots=True, frozen=True)
class PublicProductQuery:
    """Typed filters for public product browsing and search."""

    tenant_id: UUID | None = None
    search: str | None = None
    category: str | None = None
    marketplace: str | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None


@dataclass(slots=True, frozen=True)
class PublicOfferQuery:
    """Typed filters for public marketplace offer reads."""

    tenant_id: UUID | None = None
    product_id: UUID | None = None
    marketplace: str | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None


@dataclass(slots=True, frozen=True)
class PublicPriceHistoryQuery:
    """Typed filters for public price-history chart points."""

    tenant_id: UUID | None = None
    product_id: UUID | None = None
    marketplace: str | None = None
    collected_from: datetime | None = None
    collected_to: datetime | None = None


@dataclass(slots=True, frozen=True)
class PublicPriceChangeQuery:
    """Typed filters for public latest price-change feeds."""

    tenant_id: UUID | None = None
    product_id: UUID | None = None
    marketplace: str | None = None
    changed_from: datetime | None = None
    changed_to: datetime | None = None


@dataclass(slots=True, frozen=True)
class PublicCategoryQuery:
    """Typed filters for public category browsing."""

    tenant_id: UUID | None = None
    search: str | None = None


@dataclass(slots=True, frozen=True)
class OfferSummaryRead:
    """UI-safe read projection for one marketplace offer."""

    marketplace: str
    external_id: str | None
    title: str | None
    url: str | None
    price: Decimal | None
    currency: str | None
    seller_id: str | None = None
    seller_name: str | None = None
    canonical_product_id: UUID | None = None


@dataclass(slots=True, frozen=True)
class ProductSummaryRead:
    """Compact public product projection for cards and search results."""

    id: UUID
    name: str
    category: str | None
    best_offer: OfferSummaryRead | None
    offer_count: int
    marketplace_count: int
    updated_at: datetime | None


@dataclass(slots=True, frozen=True)
class ProductDetailRead:
    """Public product detail projection for product pages."""

    id: UUID
    name: str
    category: str | None
    aliases: tuple[str, ...]
    best_offer: OfferSummaryRead | None
    offer_count: int
    marketplace_count: int
    updated_at: datetime | None


@dataclass(slots=True, frozen=True)
class PriceDifferenceRead:
    """Public difference between one offer and the selected best offer."""

    offer: OfferSummaryRead
    absolute_difference: Decimal | None
    percentage_difference: Decimal | None
    reason: str | None


@dataclass(slots=True, frozen=True)
class ProductComparisonRead:
    """Public comparison projection for one canonical product."""

    product: ProductDetailRead | None
    offers: tuple[OfferSummaryRead, ...]
    best_offer: OfferSummaryRead | None
    differences: tuple[PriceDifferenceRead, ...]
    status: str


@dataclass(slots=True, frozen=True)
class PriceHistoryPointRead:
    """Public price-history chart point."""

    marketplace: str
    price: Decimal
    currency: str
    collected_at: datetime


@dataclass(slots=True, frozen=True)
class PriceChangeRead:
    """Public latest price-change projection."""

    product_id: UUID | None
    product_name: str
    marketplace: str
    old_price: Decimal
    new_price: Decimal
    currency: str
    discount_percent: Decimal
    changed_at: datetime
    url: str | None


@dataclass(slots=True, frozen=True)
class CategoryRead:
    """Public category projection for browse filters."""

    code: str
    name: str
    product_count: int
