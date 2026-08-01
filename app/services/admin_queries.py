from __future__ import annotations

from uuid import UUID

from app.repositories.queries.contracts import (
    GeneratedContentQueryRepository,
    MarketEventQueryRepository,
    PublicationQueryRepository,
)
from app.repositories.queries.models import (
    ContentQuery,
    ContentRead,
    EventQuery,
    EventRead,
    PageRequest,
    PublicationQuery,
    PublicationRead,
    ReadPage,
)


class AdminEventQueryService:
    """Application read service for market-event administration views."""

    def __init__(self, repository: MarketEventQueryRepository) -> None:
        """Bind the service to a caller-owned query contract."""
        self._repository = repository

    async def list_events(
        self,
        query: EventQuery,
        page: PageRequest,
    ) -> ReadPage[EventRead]:
        """Return a filtered event page."""
        return await self._repository.list_events(query, page)

    async def get_event(self, event_id: UUID) -> EventRead | None:
        """Return one event projection."""
        return await self._repository.get_event(event_id)


class AdminContentQueryService:
    """Application read service for generated-content administration views."""

    def __init__(self, repository: GeneratedContentQueryRepository) -> None:
        """Bind the service to a caller-owned query contract."""
        self._repository = repository

    async def list_content(
        self,
        query: ContentQuery,
        page: PageRequest,
    ) -> ReadPage[ContentRead]:
        """Return a filtered content page."""
        return await self._repository.list_content(query, page)

    async def get_content(self, content_id: UUID) -> ContentRead | None:
        """Return one content projection."""
        return await self._repository.get_content(content_id)


class AdminPublicationQueryService:
    """Application read service for publication administration views."""

    def __init__(self, repository: PublicationQueryRepository) -> None:
        """Bind the service to a caller-owned query contract."""
        self._repository = repository

    async def list_publications(
        self,
        query: PublicationQuery,
        page: PageRequest,
    ) -> ReadPage[PublicationRead]:
        """Return a filtered publication page."""
        return await self._repository.list_publications(query, page)

    async def get_publication(self, publication_id: UUID) -> PublicationRead | None:
        """Return one publication projection."""
        return await self._repository.get_publication(publication_id)
