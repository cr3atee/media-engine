from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.events import BaseEvent


class ContentPipeline(ABC):
    """Abstract interface for transforming domain events into publication text."""

    @abstractmethod
    async def process(self, event: BaseEvent) -> str:
        """Process a domain event and return ready-to-publish text."""
