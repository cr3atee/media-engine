from __future__ import annotations

from app.repositories.public_queries.contracts import PublicOfferQueryRepository
from app.repositories.public_queries.models import OfferSummaryRead, PublicOfferQuery
from app.repositories.queries.models import PageRequest, ReadPage


class PublicOfferReadService:
    """Application read service for public marketplace offer lists."""

    def __init__(self, repository: PublicOfferQueryRepository) -> None:
        """Bind the service to a caller-owned public offer query contract."""
        self._repository = repository

    async def list_offers(
        self,
        query: PublicOfferQuery,
        page: PageRequest,
    ) -> ReadPage[OfferSummaryRead]:
        """Return offer summaries for public product pages."""
        return await self._repository.list_offers(query, page)
