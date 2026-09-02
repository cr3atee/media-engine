from __future__ import annotations

from app.repositories.admin_actions import AdminActionRepository
from app.repositories.auth import (
    AuthSessionRepository,
    PasswordCredentialRepository,
    PasswordResetTokenRepository,
)
from app.repositories.base import BaseRepository, RepositoryIdentityConflictError
from app.repositories.canonical_products import CanonicalProductRepository
from app.repositories.events import MarketEventRepository
from app.repositories.generated_contents import GeneratedContentRepository
from app.repositories.marketplace_integrations import MarketplaceIntegrationRepository
from app.repositories.memberships import MembershipRepository
from app.repositories.offers import OfferRepository
from app.repositories.price_history import PriceHistoryRepository
from app.repositories.publications import PublicationRepository
from app.repositories.tenants import TenantRepository
from app.repositories.users import UserRepository

__all__ = (
    "AdminActionRepository",
    "AuthSessionRepository",
    "BaseRepository",
    "CanonicalProductRepository",
    "GeneratedContentRepository",
    "MarketEventRepository",
    "MarketplaceIntegrationRepository",
    "MembershipRepository",
    "OfferRepository",
    "PasswordCredentialRepository",
    "PasswordResetTokenRepository",
    "PriceHistoryRepository",
    "PublicationRepository",
    "RepositoryIdentityConflictError",
    "TenantRepository",
    "UserRepository",
)
