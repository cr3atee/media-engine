from __future__ import annotations

from app.api.schemas.public import (
    PublicCategory,
    PublicComparisonResult,
    PublicOfferSummary,
    PublicPriceChange,
    PublicPriceDifference,
    PublicPriceHistoryPoint,
    PublicProductCard,
    PublicProductDetail,
)
from app.comparator.result import ComparisonStatus
from app.repositories.public_queries.models import (
    CategoryRead,
    OfferSummaryRead,
    PriceChangeRead,
    PriceDifferenceRead,
    PriceHistoryPointRead,
    ProductComparisonRead,
    ProductDetailRead,
    ProductSummaryRead,
)


def public_offer_summary(offer: OfferSummaryRead) -> PublicOfferSummary:
    """Map one public offer projection to its response DTO."""
    return PublicOfferSummary(
        marketplace=offer.marketplace,
        external_id=offer.external_id,
        title=offer.title,
        url=offer.url,
        price=offer.price,
        currency=offer.currency,
        seller_id=offer.seller_id,
        seller_name=offer.seller_name,
    )


def public_product_card(product: ProductSummaryRead) -> PublicProductCard:
    """Map one product summary projection to its card response DTO."""
    return PublicProductCard(
        id=product.id,
        name=product.name,
        category=product.category,
        best_offer=(
            public_offer_summary(product.best_offer)
            if product.best_offer is not None
            else None
        ),
        offer_count=product.offer_count,
        marketplace_count=product.marketplace_count,
        updated_at=product.updated_at,
    )


def public_product_detail(product: ProductDetailRead) -> PublicProductDetail:
    """Map one product detail projection to its response DTO."""
    return PublicProductDetail(
        id=product.id,
        name=product.name,
        category=product.category,
        aliases=list(product.aliases),
        best_offer=(
            public_offer_summary(product.best_offer)
            if product.best_offer is not None
            else None
        ),
        offer_count=product.offer_count,
        marketplace_count=product.marketplace_count,
        updated_at=product.updated_at,
    )


def public_price_difference(
    difference: PriceDifferenceRead,
) -> PublicPriceDifference:
    """Map one public price-difference projection to its response DTO."""
    return PublicPriceDifference(
        offer=public_offer_summary(difference.offer),
        absolute_difference=difference.absolute_difference,
        percentage_difference=difference.percentage_difference,
        reason=difference.reason,
    )


def public_comparison_result(
    comparison: ProductComparisonRead,
) -> PublicComparisonResult:
    """Map one public comparison projection to its response DTO."""
    return PublicComparisonResult(
        product=(
            public_product_detail(comparison.product)
            if comparison.product is not None
            else None
        ),
        offers=[public_offer_summary(offer) for offer in comparison.offers],
        best_offer=(
            public_offer_summary(comparison.best_offer)
            if comparison.best_offer is not None
            else None
        ),
        differences=[
            public_price_difference(difference) for difference in comparison.differences
        ],
        status=ComparisonStatus(comparison.status),
    )


def public_price_history_point(
    point: PriceHistoryPointRead,
) -> PublicPriceHistoryPoint:
    """Map one public price-history point to its response DTO."""
    return PublicPriceHistoryPoint(
        marketplace=point.marketplace,
        price=point.price,
        currency=point.currency,
        collected_at=point.collected_at,
    )


def public_price_change(change: PriceChangeRead) -> PublicPriceChange:
    """Map one public price-change projection to its response DTO."""
    return PublicPriceChange(
        product_id=change.product_id,
        product_name=change.product_name,
        marketplace=change.marketplace,
        old_price=change.old_price,
        new_price=change.new_price,
        currency=change.currency,
        discount_percent=change.discount_percent,
        changed_at=change.changed_at,
        url=change.url,
    )


def public_category(category: CategoryRead) -> PublicCategory:
    """Map one public category projection to its response DTO."""
    return PublicCategory(
        code=category.code,
        name=category.name,
        product_count=category.product_count,
    )
