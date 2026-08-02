from __future__ import annotations

from app.domain.events import BaseEvent, PriceDropEvent


class EventScorer:
    """Calculates importance scores for domain events."""

    def score(self, event: BaseEvent) -> int:
        """Return an importance score for a known event type."""
        if not isinstance(event, PriceDropEvent):
            return 0

        discount = event.discount_percent
        if discount < 5:
            return 10
        if discount <= 10:
            return 30
        if discount <= 20:
            return 60
        if discount <= 30:
            return 80
        return 100
