from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from app.repositories.public_queries.models import (
    CategoryRead,
    OfferSummaryRead,
    PriceChangeRead,
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
from app.repositories.queries.models import PageRequest, ReadPage


class PublicProductQueryRepository(ABC):
    """Database-independent read contract for public product discovery."""

    @abstractmethod
    async def list_products(
        self,
        query: PublicProductQuery,
        page: PageRequest,
    ) -> ReadPage[ProductSummaryRead]:
        """Return a filtered, deterministically ordered public product page."""

    @abstractmethod
    async def get_product(
        self,
        product_id: UUID,
        tenant_id: UUID | None = None,
    ) -> ProductDetailRead | None:
        """Return one public product detail projection by identifier."""


class PublicOfferQueryRepository(ABC):
    """Database-independent read contract for public marketplace offers."""

    @abstractmethod
    async def list_offers(
        self,
        query: PublicOfferQuery,
        page: PageRequest,
    ) -> ReadPage[OfferSummaryRead]:
        """Return a filtered, deterministically ordered public offer page."""


class PublicComparisonQueryRepository(ABC):
    """Database-independent read contract for public comparison results."""

    @abstractmethod
    async def get_comparison(
        self,
        product_id: UUID,
        tenant_id: UUID | None = None,
    ) -> ProductComparisonRead | None:
        """Return one UI-safe comparison projection for a product."""


class PublicPriceHistoryQueryRepository(ABC):
    """Database-independent read contract for public price-history charts."""

    @abstractmethod
    async def list_price_history(
        self,
        query: PublicPriceHistoryQuery,
        page: PageRequest,
    ) -> ReadPage[PriceHistoryPointRead]:
        """Return bounded public price-history points for chart rendering."""


class PublicPriceChangeQueryRepository(ABC):
    """Database-independent read contract for public latest price changes."""

    @abstractmethod
    async def list_price_changes(
        self,
        query: PublicPriceChangeQuery,
        page: PageRequest,
    ) -> ReadPage[PriceChangeRead]:
        """Return a filtered, deterministically ordered price-change page."""


class PublicCategoryQueryRepository(ABC):
    """Database-independent read contract for public product categories."""

    @abstractmethod
    async def list_categories(
        self,
        query: PublicCategoryQuery,
        page: PageRequest,
    ) -> ReadPage[CategoryRead]:
        """Return public categories available for browsing and filters."""
