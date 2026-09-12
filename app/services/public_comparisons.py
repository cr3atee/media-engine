from __future__ import annotations

from uuid import UUID

from app.repositories.public_queries.contracts import PublicComparisonQueryRepository
from app.repositories.public_queries.models import ProductComparisonRead


class PublicComparisonReadService:
    """Application read service for public product comparison views."""

    def __init__(self, repository: PublicComparisonQueryRepository) -> None:
        """Bind the service to a caller-owned public comparison query contract."""
        self._repository = repository

    async def get_comparison(
        self,
        product_id: UUID,
        tenant_id: UUID | None = None,
    ) -> ProductComparisonRead | None:
        """Return one public comparison projection without recalculating it."""
        return await self._repository.get_comparison(product_id, tenant_id)
