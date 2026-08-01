"""Database-independent read-side query contracts and implementations."""

from app.repositories.queries.contracts import (
    DashboardQueryRepository,
    GeneratedContentQueryRepository,
    MarketEventQueryRepository,
    PublicationQueryRepository,
)
from app.repositories.queries.models import (
    ContentQuery,
    DashboardSummaryRead,
    DashboardWindow,
    EventQuery,
    PageRequest,
    PublicationQuery,
    ReadPage,
)
from app.repositories.queries.provider import (
    ReadRepositoryProvider,
    create_memory_read_provider,
    create_postgres_read_repository_scope,
)

__all__ = [
    "ContentQuery",
    "DashboardQueryRepository",
    "DashboardSummaryRead",
    "DashboardWindow",
    "EventQuery",
    "GeneratedContentQueryRepository",
    "MarketEventQueryRepository",
    "PageRequest",
    "PublicationQuery",
    "PublicationQueryRepository",
    "ReadPage",
    "ReadRepositoryProvider",
    "create_memory_read_provider",
    "create_postgres_read_repository_scope",
]
