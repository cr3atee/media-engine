from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from app.models.canonical_product import CanonicalProduct
from app.repositories.canonical_products import CanonicalProductRepository


class MemoryCanonicalProductRepository(CanonicalProductRepository):
    """In-memory repository for canonical products."""

    def __init__(self) -> None:
        """Initialize empty in-memory product storage."""
        self._products: dict[UUID, CanonicalProduct] = {}

    async def save(self, product: CanonicalProduct) -> None:
        """Store or replace a canonical product by identifier."""
        self._products[product.id] = product

    async def get_by_id(self, id: UUID) -> CanonicalProduct | None:
        """Return a canonical product by identifier when it exists."""
        return self._products.get(id)

    async def get_by_tenant_and_id(
        self,
        tenant_id: UUID,
        id: UUID,
    ) -> CanonicalProduct | None:
        """Return a canonical product only inside its owning tenant."""
        product = self._products.get(id)
        if product is None or product.tenant_id != tenant_id:
            return None
        return product

    async def list_by_tenant(self, tenant_id: UUID) -> Sequence[CanonicalProduct]:
        """Return tenant-owned canonical products in insertion order."""
        return tuple(
            product
            for product in self._products.values()
            if product.tenant_id == tenant_id
        )

    async def list_all(self) -> Sequence[CanonicalProduct]:
        """Return all canonical products in insertion order."""
        return tuple(self._products.values())
