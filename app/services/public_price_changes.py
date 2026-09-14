from __future__ import annotations

from app.repositories.public_queries.contracts import PublicPriceChangeQueryRepository
from app.repositories.public_queries.models import (
    PriceChangeRead,
    PublicPriceChangeQuery,
)
from app.repositories.queries.models import PageRequest, ReadPage


class PublicPriceChangeReadService:
    """Application read service for public latest price-change feeds."""

    def __init__(self, repository: PublicPriceChangeQueryRepository) -> None:
        """Bind the service to a caller-owned public price-change query contract."""
        self._repository = repository

    async def list_price_changes(
        self,
        query: PublicPriceChangeQuery,
        page: PageRequest,
    ) -> ReadPage[PriceChangeRead]:
        """Return public latest price-change projections."""
        return await self._repository.list_price_changes(query, page)
