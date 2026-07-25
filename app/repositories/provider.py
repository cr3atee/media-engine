from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, overload

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.canonical_products import CanonicalProductRepository
from app.repositories.memory import (
    MemoryCanonicalProductRepository,
    MemoryOfferRepository,
    MemoryPriceHistoryRepository,
)
from app.repositories.offers import OfferRepository
from app.repositories.postgres import (
    PostgresCanonicalProductRepository,
    PostgresOfferRepository,
    PostgresPriceHistoryRepository,
)
from app.repositories.price_history import PriceHistoryRepository

RepositoryBackend = Literal["memory", "postgres"]


@dataclass(slots=True)
class RepositoryProvider:
    """Container for repository implementations used by business services."""

    canonical_products: CanonicalProductRepository
    offers: OfferRepository
    price_history: PriceHistoryRepository


def create_memory_provider() -> RepositoryProvider:
    """Create a repository provider backed by in-memory implementations."""
    return RepositoryProvider(
        canonical_products=MemoryCanonicalProductRepository(),
        offers=MemoryOfferRepository(),
        price_history=MemoryPriceHistoryRepository(),
    )


def create_postgres_provider(session: AsyncSession) -> RepositoryProvider:
    """Create a repository provider backed by PostgreSQL implementations."""
    return RepositoryProvider(
        canonical_products=PostgresCanonicalProductRepository(session),
        offers=PostgresOfferRepository(session),
        price_history=PostgresPriceHistoryRepository(session),
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
