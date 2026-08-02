from __future__ import annotations

from app.repositories.postgres.postgres_admin_actions import (
    PostgresAdminActionRepository,
)
from app.repositories.postgres.postgres_canonical_products import (
    PostgresCanonicalProductRepository,
)
from app.repositories.postgres.postgres_events import PostgresMarketEventRepository
from app.repositories.postgres.postgres_generated_contents import (
    PostgresGeneratedContentRepository,
)
from app.repositories.postgres.postgres_memberships import PostgresMembershipRepository
from app.repositories.postgres.postgres_offers import PostgresOfferRepository
from app.repositories.postgres.postgres_price_history import (
    PostgresPriceHistoryRepository,
)
from app.repositories.postgres.postgres_publications import (
    PostgresPublicationRepository,
)
from app.repositories.postgres.postgres_tenants import PostgresTenantRepository
from app.repositories.postgres.postgres_users import PostgresUserRepository

__all__ = [
    "PostgresAdminActionRepository",
    "PostgresCanonicalProductRepository",
    "PostgresGeneratedContentRepository",
    "PostgresMarketEventRepository",
    "PostgresMembershipRepository",
    "PostgresOfferRepository",
    "PostgresPriceHistoryRepository",
    "PostgresPublicationRepository",
    "PostgresTenantRepository",
    "PostgresUserRepository",
]
