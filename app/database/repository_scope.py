from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.session import SessionLocal
from app.repositories.provider import RepositoryProvider, create_postgres_provider
from app.services.repository_scope import RepositoryScopeFactory


def create_postgres_repository_scope(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> RepositoryScopeFactory:
    """Create a repository scope owning one PostgreSQL transaction per entry."""

    @asynccontextmanager
    async def repository_scope() -> AsyncIterator[RepositoryProvider]:
        async with session_factory() as session:
            async with session.begin():
                yield create_postgres_provider(session)

    return repository_scope
