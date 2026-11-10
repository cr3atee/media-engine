"""Public consumer read-side query contracts for Market Terminal."""

from app.repositories.public_queries.contracts import (
    PublicCatalogHubQueryRepository,
    PublicCategoryQueryRepository,
    PublicComparisonQueryRepository,
    PublicOfferQueryRepository,
    PublicPriceChangeQueryRepository,
    PublicPriceHistoryQueryRepository,
    PublicProductQueryRepository,
)
from app.repositories.public_queries.models import (
    CatalogHubRead,
    CatalogSectionRead,
    CategoryRead,
    OfferSummaryRead,
    PriceChangeRead,
    PriceDifferenceRead,
    PriceHistoryPointRead,
    ProductComparisonRead,
    ProductDetailRead,
    ProductSummaryRead,
    PublicCatalogHubQuery,
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
from app.repositories.public_queries.repository_backed import (
    RepositoryBackedPublicReadRepository,
    create_repository_backed_public_read_provider,
    create_repository_backed_public_read_scope_factory,
)

__all__ = [
    "CategoryRead",
    "CatalogHubRead",
    "CatalogSectionRead",
    "OfferSummaryRead",
    "PriceChangeRead",
    "PriceDifferenceRead",
    "PriceHistoryPointRead",
    "ProductComparisonRead",
    "ProductDetailRead",
    "ProductSummaryRead",
    "PublicCategoryQuery",
    "PublicCategoryQueryRepository",
    "PublicCatalogHubQuery",
    "PublicCatalogHubQueryRepository",
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
    "RepositoryBackedPublicReadRepository",
    "create_repository_backed_public_read_provider",
    "create_repository_backed_public_read_scope_factory",
]
