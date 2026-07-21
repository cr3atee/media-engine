from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from uuid import UUID

from app.models.canonical_product import CanonicalProduct
from app.repositories.base import BaseRepository


class CanonicalProductRepository(BaseRepository):
    """Abstract storage contract for canonical products."""

    @abstractmethod
    def save(self, product: CanonicalProduct) -> None:
        """Persist or update a canonical product."""

    @abstractmethod
    def get_by_id(self, id: UUID) -> CanonicalProduct | None:
        """Return a canonical product by identifier when it exists."""

    @abstractmethod
    def list_all(self) -> Sequence[CanonicalProduct]:
        """Return all canonical products."""
