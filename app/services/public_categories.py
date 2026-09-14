from __future__ import annotations

from app.repositories.public_queries.contracts import PublicCategoryQueryRepository
from app.repositories.public_queries.models import CategoryRead, PublicCategoryQuery
from app.repositories.queries.models import PageRequest, ReadPage


class PublicCategoryReadService:
    """Application read service for public category browse filters."""

    def __init__(self, repository: PublicCategoryQueryRepository) -> None:
        """Bind the service to a caller-owned public category query contract."""
        self._repository = repository

    async def list_categories(
        self,
        query: PublicCategoryQuery,
        page: PageRequest,
    ) -> ReadPage[CategoryRead]:
        """Return public category summaries for browse and filter UIs."""
        return await self._repository.list_categories(query, page)
