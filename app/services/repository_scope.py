from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from copy import deepcopy
from dataclasses import fields

from app.repositories.provider import RepositoryProvider, create_memory_provider

type RepositoryScopeFactory = Callable[
    [],
    AbstractAsyncContextManager[RepositoryProvider],
]


def create_memory_repository_scope(
    provider: RepositoryProvider | None = None,
) -> RepositoryScopeFactory:
    """Create a serialized memory scope with rollback on command failure."""
    repository_provider = provider or create_memory_provider()
    transaction_lock = asyncio.Lock()

    @asynccontextmanager
    async def repository_scope() -> AsyncIterator[RepositoryProvider]:
        async with transaction_lock:
            snapshot = deepcopy(repository_provider)
            try:
                yield repository_provider
            except BaseException:
                for provider_field in fields(RepositoryProvider):
                    setattr(
                        repository_provider,
                        provider_field.name,
                        getattr(snapshot, provider_field.name),
                    )
                raise

    return repository_scope
