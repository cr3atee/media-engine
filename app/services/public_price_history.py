from __future__ import annotations

from app.repositories.public_queries.contracts import PublicPriceHistoryQueryRepository
from app.repositories.public_queries.models import (
    PriceHistoryPointRead,
    PublicPriceHistoryQuery,
)
from app.repositories.queries.models import PageRequest, ReadPage


class PublicPriceHistoryReadService:
    """Application read service for public product price-history charts."""

    def __init__(self, repository: PublicPriceHistoryQueryRepository) -> None:
        """Bind the service to a caller-owned public price-history query contract."""
        self._repository = repository

    async def list_price_history(
        self,
        query: PublicPriceHistoryQuery,
        page: PageRequest,
    ) -> ReadPage[PriceHistoryPointRead]:
        """Return bounded price-history points without mutating lifecycle state."""
        return await self._repository.list_price_history(query, page)
