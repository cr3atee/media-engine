from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.correlation import RequestCorrelationMiddleware
from app.api.errors import (
    ApiError,
    api_error_handler,
    http_error_handler,
    unexpected_error_handler,
    validation_error_handler,
)
from app.api.routes.admin_content import (
    event_content_router,
)
from app.api.routes.admin_content import (
    router as admin_content_router,
)
from app.api.routes.admin_events import router as admin_events_router
from app.api.routes.admin_publications import (
    event_publication_router,
)
from app.api.routes.admin_publications import (
    router as admin_publications_router,
)
from app.api.routes.health import router as health_router
from app.config.settings import AdminApiSettings, settings
from app.core.logging import setup_logging
from app.repositories.queries.provider import (
    ReadRepositoryScopeFactory,
    create_postgres_read_repository_scope,
)

setup_logging()


def create_app(
    *,
    admin_api_settings: AdminApiSettings | None = None,
    read_repository_scope_factory: ReadRepositoryScopeFactory | None = None,
) -> FastAPI:
    """Create the application with one explicit read-side composition root."""
    configuration = admin_api_settings or settings.admin_api
    application = FastAPI(
        openapi_url="/openapi.json" if configuration.api_docs_enabled else None,
        docs_url="/docs" if configuration.api_docs_enabled else None,
        redoc_url="/redoc" if configuration.api_docs_enabled else None,
    )
    application.state.admin_api_settings = configuration
    application.state.read_repository_scope_factory = (
        read_repository_scope_factory or create_postgres_read_repository_scope()
    )
    application.add_middleware(
        RequestCorrelationMiddleware,
        settings=configuration,
    )
    application.add_exception_handler(ApiError, api_error_handler)
    application.add_exception_handler(RequestValidationError, validation_error_handler)
    application.add_exception_handler(ValidationError, validation_error_handler)
    application.add_exception_handler(StarletteHTTPException, http_error_handler)
    application.add_exception_handler(Exception, unexpected_error_handler)
    application.include_router(health_router)
    application.include_router(admin_events_router)
    application.include_router(admin_content_router)
    application.include_router(admin_publications_router)
    application.include_router(event_content_router)
    application.include_router(event_publication_router)
    return application


app = create_app()


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok"}
