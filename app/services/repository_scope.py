from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from app.repositories.provider import RepositoryProvider, create_memory_provider

type RepositoryScopeFactory = Callable[
    [],
    AbstractAsyncContextManager[RepositoryProvider],
]


def create_memory_repository_scope(
    provider: RepositoryProvider | None = None,
) -> RepositoryScopeFactory:
    """Create a reusable no-op repository scope backed by memory storage."""
    repository_provider = provider or create_memory_provider()

    @asynccontextmanager
    async def repository_scope() -> AsyncIterator[RepositoryProvider]:
        yield repository_provider

    return repository_scope
