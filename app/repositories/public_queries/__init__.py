"""Public consumer read-side query contracts for Market Terminal."""

from app.repositories.public_queries.contracts import (
    PublicCategoryQueryRepository,
    PublicComparisonQueryRepository,
    PublicOfferQueryRepository,
    PublicPriceChangeQueryRepository,
    PublicPriceHistoryQueryRepository,
    PublicProductQueryRepository,
)
from app.repositories.public_queries.models import (
    CategoryRead,
    OfferSummaryRead,
    PriceChangeRead,
    PriceDifferenceRead,
    PriceHistoryPointRead,
    ProductComparisonRead,
    ProductDetailRead,
    ProductSummaryRead,
    PublicCategoryQuery,
    PublicOfferQuery,
    PublicPriceChangeQuery,
    PublicPriceHistoryQuery,
    PublicProductQuery,
)
from app.repositories.public_queries.provider import (
    PublicReadRepositoryProvider,
    PublicReadRepositoryScopeFactory,
)

__all__ = [
    "CategoryRead",
    "OfferSummaryRead",
    "PriceChangeRead",
    "PriceDifferenceRead",
    "PriceHistoryPointRead",
    "ProductComparisonRead",
    "ProductDetailRead",
    "ProductSummaryRead",
    "PublicCategoryQuery",
    "PublicCategoryQueryRepository",
    "PublicComparisonQueryRepository",
    "PublicOfferQuery",
    "PublicOfferQueryRepository",
    "PublicPriceChangeQuery",
    "PublicPriceChangeQueryRepository",
    "PublicPriceHistoryQuery",
    "PublicPriceHistoryQueryRepository",
    "PublicProductQuery",
    "PublicProductQueryRepository",
    "PublicReadRepositoryProvider",
    "PublicReadRepositoryScopeFactory",
]
