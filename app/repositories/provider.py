from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, overload

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.admin_actions import AdminActionRepository
from app.repositories.canonical_products import CanonicalProductRepository
from app.repositories.events import MarketEventRepository
from app.repositories.generated_contents import GeneratedContentRepository
from app.repositories.memberships import MembershipRepository
from app.repositories.memory import (
    MemoryAdminActionRepository,
    MemoryCanonicalProductRepository,
    MemoryGeneratedContentRepository,
    MemoryMarketEventRepository,
    MemoryMembershipRepository,
    MemoryOfferRepository,
    MemoryPriceHistoryRepository,
    MemoryPublicationRepository,
    MemoryTenantRepository,
    MemoryUserRepository,
)
from app.repositories.offers import OfferRepository
from app.repositories.postgres import (
    PostgresAdminActionRepository,
    PostgresCanonicalProductRepository,
    PostgresGeneratedContentRepository,
    PostgresMarketEventRepository,
    PostgresMembershipRepository,
    PostgresOfferRepository,
    PostgresPriceHistoryRepository,
    PostgresPublicationRepository,
    PostgresTenantRepository,
    PostgresUserRepository,
)
from app.repositories.price_history import PriceHistoryRepository
from app.repositories.publications import PublicationRepository
from app.repositories.tenants import TenantRepository
from app.repositories.users import UserRepository

RepositoryBackend = Literal["memory", "postgres"]


@dataclass(slots=True)
class RepositoryProvider:
    """Container for repository implementations used by business services."""

    canonical_products: CanonicalProductRepository
    offers: OfferRepository
    price_history: PriceHistoryRepository
    events: MarketEventRepository
    generated_contents: GeneratedContentRepository
    publications: PublicationRepository
    admin_actions: AdminActionRepository = field(
        default_factory=MemoryAdminActionRepository,
    )
    users: UserRepository = field(default_factory=MemoryUserRepository)
    tenants: TenantRepository = field(default_factory=MemoryTenantRepository)
    memberships: MembershipRepository = field(
        default_factory=MemoryMembershipRepository,
    )


def create_memory_provider() -> RepositoryProvider:
    """Create a repository provider backed by in-memory implementations."""
    return RepositoryProvider(
        admin_actions=MemoryAdminActionRepository(),
        canonical_products=MemoryCanonicalProductRepository(),
        offers=MemoryOfferRepository(),
        price_history=MemoryPriceHistoryRepository(),
        events=MemoryMarketEventRepository(),
        generated_contents=MemoryGeneratedContentRepository(),
        publications=MemoryPublicationRepository(),
        users=MemoryUserRepository(),
        tenants=MemoryTenantRepository(),
        memberships=MemoryMembershipRepository(),
    )


def create_postgres_provider(session: AsyncSession) -> RepositoryProvider:
    """Create a repository provider backed by PostgreSQL implementations."""
    return RepositoryProvider(
        admin_actions=PostgresAdminActionRepository(session),
        canonical_products=PostgresCanonicalProductRepository(session),
        offers=PostgresOfferRepository(session),
        price_history=PostgresPriceHistoryRepository(session),
        events=PostgresMarketEventRepository(session),
        generated_contents=PostgresGeneratedContentRepository(session),
        publications=PostgresPublicationRepository(session),
        users=PostgresUserRepository(session),
        tenants=PostgresTenantRepository(session),
        memberships=PostgresMembershipRepository(session),
    )


@overload
def create_repository_provider(
    backend: Literal["memory"] = "memory",
    session: None = None,
) -> RepositoryProvider: ...


@overload
def create_repository_provider(
    backend: Literal["postgres"],
    session: AsyncSession,
) -> RepositoryProvider: ...


def create_repository_provider(
    backend: RepositoryBackend = "memory",
    session: AsyncSession | None = None,
) -> RepositoryProvider:
    """Create a repository provider for the selected storage backend."""
    if backend == "memory":
        return create_memory_provider()

    if session is None:
        msg = "AsyncSession is required for postgres repositories."
        raise ValueError(msg)

    return create_postgres_provider(session)
