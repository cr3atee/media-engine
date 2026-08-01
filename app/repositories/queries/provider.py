from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.session import SessionLocal
from app.repositories.queries.contracts import (
    DashboardQueryRepository,
    GeneratedContentQueryRepository,
    MarketEventQueryRepository,
    PublicationQueryRepository,
)
from app.repositories.queries.memory import (
    MemoryDashboardQueryRepository,
    MemoryGeneratedContentQueryRepository,
    MemoryMarketEventQueryRepository,
    MemoryPublicationQueryRepository,
)
from app.repositories.queries.models import (
    ContentRead,
    EventRead,
    PublicationRead,
)
from app.repositories.queries.postgres import (
    PostgresDashboardQueryRepository,
    PostgresGeneratedContentQueryRepository,
    PostgresMarketEventQueryRepository,
    PostgresPublicationQueryRepository,
)


@dataclass(slots=True, frozen=True)
class ReadRepositoryProvider:
    """Container for read-side repository implementations."""

    events: MarketEventQueryRepository
    content: GeneratedContentQueryRepository
    publications: PublicationQueryRepository
    dashboard: DashboardQueryRepository


class ReadRepositoryScopeFactory(Protocol):
    """Callable async-context-manager contract for one read transaction."""

    def __call__(self) -> AbstractAsyncContextManager[ReadRepositoryProvider]:
        """Return an async context manager yielding a read provider."""
        ...


def create_memory_read_provider(
    *,
    events: tuple[EventRead, ...] = (),
    content: tuple[ContentRead, ...] = (),
    publications: tuple[PublicationRead, ...] = (),
) -> ReadRepositoryProvider:
    """Create isolated memory query repositories for tests and local demos."""
    return ReadRepositoryProvider(
        events=MemoryMarketEventQueryRepository(events),
        content=MemoryGeneratedContentQueryRepository(content),
        publications=MemoryPublicationQueryRepository(publications),
        dashboard=MemoryDashboardQueryRepository(
            events=events,
            content=content,
            publications=publications,
        ),
    )


def create_postgres_read_repository_scope(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> Callable[[], AbstractAsyncContextManager[ReadRepositoryProvider]]:
    """Create a scope that owns one short PostgreSQL read transaction."""

    @asynccontextmanager
    async def scope() -> AsyncIterator[ReadRepositoryProvider]:
        async with session_factory() as session:
            async with session.begin():
                yield ReadRepositoryProvider(
                    events=PostgresMarketEventQueryRepository(session),
                    content=PostgresGeneratedContentQueryRepository(session),
                    publications=PostgresPublicationQueryRepository(session),
                    dashboard=PostgresDashboardQueryRepository(session),
                )

    return scope
