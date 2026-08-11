from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from uuid import UUID

from app.models.canonical_product import CanonicalProduct
from app.repositories.base import BaseRepository


class CanonicalProductRepository(BaseRepository):
    """Abstract storage contract for canonical products."""

    @abstractmethod
    async def save(self, product: CanonicalProduct) -> None:
        """Persist or update a canonical product."""

    @abstractmethod
    async def get_by_id(self, id: UUID) -> CanonicalProduct | None:
        """Return a canonical product by identifier when it exists."""

    async def get_by_tenant_and_id(
        self,
        tenant_id: UUID,
        id: UUID,
    ) -> CanonicalProduct | None:
        """Return one canonical product only when it belongs to the tenant."""
        product = await self.get_by_id(id)
        if product is None or product.tenant_id != tenant_id:
            return None
        return product

    async def list_by_tenant(self, tenant_id: UUID) -> Sequence[CanonicalProduct]:
        """Return canonical products owned by one tenant."""
        return tuple(
            product
            for product in await self.list_all()
            if product.tenant_id == tenant_id
        )

    @abstractmethod
    async def list_all(self) -> Sequence[CanonicalProduct]:
        """Return all canonical products."""
