from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.session import SessionLocal
from app.repositories.provider import create_postgres_provider
from app.repositories.public_queries.provider import (
    PublicReadRepositoryProvider,
    PublicReadRepositoryScopeFactory,
)
from app.repositories.public_queries.repository_backed import (
    create_repository_backed_public_read_provider,
)


def create_postgres_public_read_repository_scope(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> PublicReadRepositoryScopeFactory:
    """Create a scope that serves public reads through PostgreSQL repositories."""

    @asynccontextmanager
    async def scope() -> AsyncIterator[PublicReadRepositoryProvider]:
        async with session_factory() as session:
            async with session.begin():
                yield create_repository_backed_public_read_provider(
                    create_postgres_provider(session),
                )

    return scope
