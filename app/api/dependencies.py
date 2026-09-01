from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Annotated, cast
from uuid import UUID

from fastapi import Depends, Header, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.auth import get_admin_settings
from app.api.errors import ApiError
from app.config.settings import AuthSettings
from app.domain.auth import AuthenticatedPrincipal, Permission, TenantContext
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
from app.services.auth_tokens import AuthTokenError, SignedAccessTokenService
from app.services.authentication import AuthenticationError, AuthenticationService
from app.services.authorization import AuthorizationError, AuthorizationService
from app.services.passwords import PasswordHasher
from app.services.repository_scope import RepositoryScopeFactory

_seller_bearer = HTTPBearer(
    scheme_name="SellerBearerAuth",
    description="Short-lived seller access token.",
    auto_error=False,
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


async def get_authentication_service(request: Request) -> AuthenticationService:
    """Build the seller authentication service from app configuration."""
    configuration = get_auth_settings(request)
    secret = configuration.access_token_secret.get_secret_value()
    try:
        token_service = SignedAccessTokenService(
            secret=secret,
            ttl_seconds=configuration.access_token_ttl_seconds,
            issuer=configuration.token_issuer,
            audience=configuration.token_audience,
        )
        password_hasher = PasswordHasher(
            iterations=configuration.password_hash_iterations,
        )
    except ValueError as exc:
        raise ApiError(
            503,
            "authentication_unavailable",
            "Seller authentication is not configured.",
        ) from exc
    return AuthenticationService(
        _repository_scope_factory(request),
        token_service,
        password_hasher,
        access_token_ttl_seconds=configuration.access_token_ttl_seconds,
        refresh_token_ttl_seconds=configuration.refresh_token_ttl_seconds,
        password_reset_token_ttl_seconds=(
            configuration.password_reset_token_ttl_seconds
        ),
    )


async def get_authorization_service(request: Request) -> AuthorizationService:
    """Build the tenant authorization service from app repositories."""
    return AuthorizationService(_repository_scope_factory(request))


async def require_seller_principal(
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(_seller_bearer),
    ] = None,
) -> AuthenticatedPrincipal:
    """Require a current seller bearer token."""
    if credentials is None:
        raise ApiError(
            401,
            "authentication_required",
            "Valid seller authentication is required.",
        )
    try:
        return await service.authenticate_access_token(credentials.credentials)
    except AuthTokenError as exc:
        raise ApiError(401, exc.code, exc.message) from exc
    except AuthenticationError as exc:
        raise ApiError(exc.status_code, exc.code, exc.message) from exc


def get_auth_settings(request: Request) -> AuthSettings:
    """Return request-scoped auth settings, allowing explicit test composition."""
    value = getattr(request.app.state, "auth_settings", None)
    if isinstance(value, AuthSettings):
        return value
    from app.config.settings import settings

    return settings.auth


def _repository_scope_factory(request: Request) -> RepositoryScopeFactory:
    factory = getattr(request.app.state, "repository_scope_factory", None)
    if factory is None:
        from app.database.repository_scope import create_postgres_repository_scope

        factory = create_postgres_repository_scope()
    return cast(RepositoryScopeFactory, factory)


def require_tenant_permission(
    permission: Permission,
) -> Callable[..., Awaitable[TenantContext]]:
    """Build a FastAPI dependency that resolves a permitted tenant context."""

    async def dependency(
        tenant_id: UUID,
        principal: Annotated[
            AuthenticatedPrincipal,
            Depends(require_seller_principal),
        ],
        service: Annotated[
            AuthorizationService,
            Depends(get_authorization_service),
        ],
    ) -> TenantContext:
        try:
            return await service.require_tenant_context(
                principal,
                tenant_id,
                permission,
            )
        except AuthorizationError as exc:
            raise map_authorization_error(exc) from exc

    return dependency


def map_authentication_error(error: AuthenticationError) -> ApiError:
    """Map service authentication errors to the public API envelope."""
    return ApiError(error.status_code, error.code, error.message)


def map_authorization_error(error: AuthorizationError) -> ApiError:
    """Map service authorization errors to the public API envelope."""
    return ApiError(error.status_code, error.code, error.message)
