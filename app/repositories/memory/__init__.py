from __future__ import annotations

from app.repositories.memory.memory_admin_actions import MemoryAdminActionRepository
from app.repositories.memory.memory_canonical_products import (
    MemoryCanonicalProductRepository,
)
from app.repositories.memory.memory_events import MemoryMarketEventRepository
from app.repositories.memory.memory_generated_contents import (
    MemoryGeneratedContentRepository,
)
from app.repositories.memory.memory_memberships import MemoryMembershipRepository
from app.repositories.memory.memory_offers import MemoryOfferRepository
from app.repositories.memory.memory_price_history import MemoryPriceHistoryRepository
from app.repositories.memory.memory_publications import MemoryPublicationRepository
from app.repositories.memory.memory_tenants import MemoryTenantRepository
from app.repositories.memory.memory_users import MemoryUserRepository

__all__ = (
    "MemoryAdminActionRepository",
    "MemoryCanonicalProductRepository",
    "MemoryGeneratedContentRepository",
    "MemoryMarketEventRepository",
    "MemoryMembershipRepository",
    "MemoryOfferRepository",
    "MemoryPriceHistoryRepository",
    "MemoryPublicationRepository",
    "MemoryTenantRepository",
    "MemoryUserRepository",
)
