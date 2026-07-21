from __future__ import annotations

from dataclasses import dataclass

from app.repositories.canonical_products import CanonicalProductRepository
from app.repositories.memory import (
    MemoryCanonicalProductRepository,
    MemoryOfferRepository,
    MemoryPriceHistoryRepository,
)
from app.repositories.offers import OfferRepository
from app.repositories.price_history import PriceHistoryRepository


@dataclass(slots=True)
class RepositoryProvider:
    """Container for repository implementations used by business services."""

    canonical_products: CanonicalProductRepository
    offers: OfferRepository
    price_history: PriceHistoryRepository


def create_memory_provider() -> RepositoryProvider:
    """Create a repository provider backed by in-memory implementations."""
    return RepositoryProvider(
        canonical_products=MemoryCanonicalProductRepository(),
        offers=MemoryOfferRepository(),
        price_history=MemoryPriceHistoryRepository(),
    )
