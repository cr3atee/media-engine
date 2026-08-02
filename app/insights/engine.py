from __future__ import annotations

from app.domain.events import BaseEvent


class InsightEngine:
    """Selects domain events that are worth further publication processing.

    In future iterations this class will be responsible for finding interesting
    events, removing duplicates, merging similar events, calculating event
    importance, selecting events for publication, and preparing data for daily
    and weekly digests.
    """

    def select_events(self, events: list[BaseEvent]) -> list[BaseEvent]:
        """Return selected events for publication or digest preparation."""
        return events
