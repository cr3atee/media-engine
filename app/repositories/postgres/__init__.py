from __future__ import annotations

from app.repositories.postgres.postgres_canonical_products import (
    PostgresCanonicalProductRepository,
)
from app.repositories.postgres.postgres_events import PostgresMarketEventRepository
from app.repositories.postgres.postgres_offers import PostgresOfferRepository
from app.repositories.postgres.postgres_price_history import (
    PostgresPriceHistoryRepository,
)

__all__ = [
    "PostgresCanonicalProductRepository",
    "PostgresMarketEventRepository",
    "PostgresOfferRepository",
    "PostgresPriceHistoryRepository",
]
