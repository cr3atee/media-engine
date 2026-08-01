from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from typing import Annotated, cast

from fastapi import Depends, Header, Request

from app.api.auth import get_admin_settings
from app.api.errors import ApiError
from app.repositories.queries.provider import (
    ReadRepositoryProvider,
    ReadRepositoryScopeFactory,
    create_postgres_read_repository_scope,
)
from app.services.admin_mutations import AdminMutationService
from app.services.admin_queries import (
    AdminContentQueryService,
    AdminDashboardQueryService,
    AdminEventQueryService,
    AdminPublicationQueryService,
)
from app.services.repository_scope import RepositoryScopeFactory


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


async def get_dashboard_query_service(
    repositories: Annotated[
        ReadRepositoryProvider,
        Depends(get_read_repositories),
    ],
) -> AdminDashboardQueryService:
    """Build a dashboard query service from a request-scoped provider."""
    return AdminDashboardQueryService(repositories.dashboard)


async def get_admin_mutation_service(request: Request) -> AdminMutationService:
    """Build the guarded mutation service from the application scope factory."""
    factory = getattr(request.app.state, "repository_scope_factory", None)
    if factory is None:
        from app.database.repository_scope import create_postgres_repository_scope

        factory = create_postgres_repository_scope()
    scope_factory = cast(RepositoryScopeFactory, factory)
    from app.config.settings import settings

    maximum_attempts = getattr(
        request.app.state,
        "maximum_publication_attempts",
        settings.telegram.maximum_attempts,
    )
    return AdminMutationService(
        scope_factory,
        maximum_publication_attempts=int(maximum_attempts),
    )


async def require_idempotency_key(
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        ),
    ],
) -> str:
    """Return one explicitly validated mutation idempotency key."""
    return idempotency_key


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
