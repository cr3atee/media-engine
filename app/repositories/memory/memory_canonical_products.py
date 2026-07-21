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

    def save(self, product: CanonicalProduct) -> None:
        """Store or replace a canonical product by identifier."""
        self._products[product.id] = product

    def get_by_id(self, id: UUID) -> CanonicalProduct | None:
        """Return a canonical product by identifier when it exists."""
        return self._products.get(id)

    def list_all(self) -> Sequence[CanonicalProduct]:
        """Return all canonical products in insertion order."""
        return tuple(self._products.values())
