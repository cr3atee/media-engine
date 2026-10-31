from __future__ import annotations

from app.repositories.public_queries.contracts import PublicCatalogHubQueryRepository
from app.repositories.public_queries.models import CatalogHubRead, PublicCatalogHubQuery
from app.repositories.queries.models import PageRequest, ReadPage


class PublicCatalogHubReadService:
    """Application read service for verified game and service hubs."""

    def __init__(self, repository: PublicCatalogHubQueryRepository) -> None:
        """Bind the service to a caller-owned public hub query contract."""
        self._repository = repository

    async def list_catalog_hubs(
        self,
        query: PublicCatalogHubQuery,
        page: PageRequest,
    ) -> ReadPage[CatalogHubRead]:
        """Return only hubs represented by consistently classified products."""
        return await self._repository.list_catalog_hubs(query, page)
