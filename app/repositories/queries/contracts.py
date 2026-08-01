from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

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


class MarketEventQueryRepository(ABC):
    """Database-independent read contract for durable market events."""

    @abstractmethod
    async def list_events(
        self,
        query: EventQuery,
        page: PageRequest,
    ) -> ReadPage[EventRead]:
        """Return a filtered, deterministically ordered event page."""

    @abstractmethod
    async def get_event(self, event_id: UUID) -> EventRead | None:
        """Return one event read projection by technical identifier."""


class GeneratedContentQueryRepository(ABC):
    """Database-independent read contract for generated content."""

    @abstractmethod
    async def list_content(
        self,
        query: ContentQuery,
        page: PageRequest,
    ) -> ReadPage[ContentRead]:
        """Return a filtered, deterministically ordered content page."""

    @abstractmethod
    async def get_content(self, content_id: UUID) -> ContentRead | None:
        """Return one content read projection by technical identifier."""


class PublicationQueryRepository(ABC):
    """Database-independent read contract for publication state."""

    @abstractmethod
    async def list_publications(
        self,
        query: PublicationQuery,
        page: PageRequest,
    ) -> ReadPage[PublicationRead]:
        """Return a filtered, deterministically ordered publication page."""

    @abstractmethod
    async def get_publication(self, publication_id: UUID) -> PublicationRead | None:
        """Return one publication read projection by technical identifier."""
