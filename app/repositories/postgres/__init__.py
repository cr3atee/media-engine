from __future__ import annotations

from app.repositories.postgres.postgres_canonical_products import (
    PostgresCanonicalProductRepository,
)
from app.repositories.postgres.postgres_events import PostgresMarketEventRepository
from app.repositories.postgres.postgres_generated_contents import (
    PostgresGeneratedContentRepository,
)
from app.repositories.postgres.postgres_offers import PostgresOfferRepository
from app.repositories.postgres.postgres_price_history import (
    PostgresPriceHistoryRepository,
)
from app.repositories.postgres.postgres_publications import (
    PostgresPublicationRepository,
)

__all__ = [
    "PostgresCanonicalProductRepository",
    "PostgresGeneratedContentRepository",
    "PostgresMarketEventRepository",
    "PostgresOfferRepository",
    "PostgresPriceHistoryRepository",
    "PostgresPublicationRepository",
]
