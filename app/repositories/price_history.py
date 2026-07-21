from __future__ import annotations

from app.repositories.base import BaseRepository


class PriceHistoryRepository(BaseRepository):
    """Abstract storage contract for future price history persistence."""
