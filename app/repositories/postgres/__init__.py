from __future__ import annotations

from app.repositories.postgres.postgres_canonical_products import (
    PostgresCanonicalProductRepository,
)
from app.repositories.postgres.postgres_offers import PostgresOfferRepository

__all__ = ["PostgresCanonicalProductRepository", "PostgresOfferRepository"]
