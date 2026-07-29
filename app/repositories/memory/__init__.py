from __future__ import annotations

from app.repositories.memory.memory_canonical_products import (
    MemoryCanonicalProductRepository,
)
from app.repositories.memory.memory_events import MemoryMarketEventRepository
from app.repositories.memory.memory_generated_contents import (
    MemoryGeneratedContentRepository,
)
from app.repositories.memory.memory_offers import MemoryOfferRepository
from app.repositories.memory.memory_price_history import MemoryPriceHistoryRepository
from app.repositories.memory.memory_publications import MemoryPublicationRepository

__all__ = (
    "MemoryCanonicalProductRepository",
    "MemoryGeneratedContentRepository",
    "MemoryMarketEventRepository",
    "MemoryOfferRepository",
    "MemoryPriceHistoryRepository",
    "MemoryPublicationRepository",
)
