from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from typing import Annotated, cast

from fastapi import Depends, Request

from app.api.auth import get_admin_settings
from app.api.errors import ApiError
from app.repositories.queries.provider import (
    ReadRepositoryProvider,
    ReadRepositoryScopeFactory,
    create_postgres_read_repository_scope,
)
from app.services.admin_queries import (
    AdminContentQueryService,
    AdminEventQueryService,
    AdminPublicationQueryService,
)


async def get_read_repositories(
    request: Request,
) -> AsyncIterator[ReadRepositoryProvider]:
    """Yield one caller-owned read repository scope for an API request."""
    factory = getattr(request.app.state, "read_repository_scope_factory", None)
    if factory is None:
        factory = create_postgres_read_repository_scope()
    scope_factory = cast(ReadRepositoryScopeFactory, factory)
    context = scope_factory()
    if not isinstance(context, AbstractAsyncContextManager):
        raise ApiError(
            500,
            "internal_error",
            "Read repository composition is invalid.",
        )
    async with context as provider:
        yield provider


async def get_event_query_service(
    repositories: Annotated[
        ReadRepositoryProvider,
        Depends(get_read_repositories),
    ],
) -> AdminEventQueryService:
    """Build an event query service from a request-scoped provider."""
    return AdminEventQueryService(repositories.events)


async def get_content_query_service(
    repositories: Annotated[
        ReadRepositoryProvider,
        Depends(get_read_repositories),
    ],
) -> AdminContentQueryService:
    """Build a content query service from a request-scoped provider."""
    return AdminContentQueryService(repositories.content)


async def get_publication_query_service(
    repositories: Annotated[
        ReadRepositoryProvider,
        Depends(get_read_repositories),
    ],
) -> AdminPublicationQueryService:
    """Build a publication query service from a request-scoped provider."""
    return AdminPublicationQueryService(repositories.publications)


def validate_page_size(request: Request, page_size: int) -> None:
    """Apply configured page-size bounds after DTO parsing."""
    configuration = get_admin_settings(request)
    if page_size > configuration.maximum_page_size:
        raise ApiError(
            422,
            "invalid_page_size",
            "Requested page size exceeds the configured maximum.",
            details={"maximum": configuration.maximum_page_size},
        )
