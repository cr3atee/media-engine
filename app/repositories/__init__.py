from __future__ import annotations

from app.repositories.base import BaseRepository
from app.repositories.canonical_products import CanonicalProductRepository
from app.repositories.offers import OfferRepository
from app.repositories.price_history import PriceHistoryRepository

__all__ = (
    "BaseRepository",
    "CanonicalProductRepository",
    "OfferRepository",
    "PriceHistoryRepository",
)
