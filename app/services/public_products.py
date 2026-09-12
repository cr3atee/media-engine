from __future__ import annotations

from uuid import UUID

from app.repositories.public_queries.contracts import PublicProductQueryRepository
from app.repositories.public_queries.models import (
    ProductDetailRead,
    ProductSummaryRead,
    PublicProductQuery,
)
from app.repositories.queries.models import PageRequest, ReadPage


class PublicProductReadService:
    """Application read service for public product discovery views."""

    def __init__(self, repository: PublicProductQueryRepository) -> None:
        """Bind the service to a caller-owned public product query contract."""
        self._repository = repository

    async def list_products(
        self,
        query: PublicProductQuery,
        page: PageRequest,
    ) -> ReadPage[ProductSummaryRead]:
        """Return product-card projections for public browse and search pages."""
        return await self._repository.list_products(query, page)

    async def get_product(
        self,
        product_id: UUID,
        tenant_id: UUID | None = None,
    ) -> ProductDetailRead | None:
        """Return one public product-detail projection."""
        return await self._repository.get_product(product_id, tenant_id)
