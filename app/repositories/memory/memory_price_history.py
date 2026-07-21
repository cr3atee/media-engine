from __future__ import annotations

from app.repositories.price_history import PriceHistoryRepository


class MemoryPriceHistoryRepository(PriceHistoryRepository):
    """In-memory placeholder for the future price history repository contract."""
