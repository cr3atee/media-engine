from __future__ import annotations

from app.analytics.models import PriceChange
from app.domain.events import PriceDropEvent


class EventBuilder:
    """Builds domain events from analytics results."""

    def build(self, change: PriceChange) -> PriceDropEvent | None:
        """Return a price drop event for decreased prices only."""
        if not change.is_price_drop:
            return None
        if change.marketplace is None or change.product_identifier is None:
            return None

        return PriceDropEvent(
            title=change.product_identifier,
            marketplace=change.marketplace,
            old_price=float(change.old_price),
            new_price=float(change.new_price),
        )
