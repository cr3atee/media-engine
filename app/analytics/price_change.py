from __future__ import annotations

from app.analytics.models import PriceChange
from app.domain.price_snapshot import PriceSnapshot


class PriceChangeDetector:
    """Detects price changes between two price snapshots."""

    def detect(
        self,
        previous: PriceSnapshot,
        current: PriceSnapshot,
    ) -> PriceChange | None:
        """Return price change data when snapshot prices differ."""
        if previous.price == current.price:
            return None

        difference = current.price - previous.price
        percentage = (difference / previous.price) * 100

        return PriceChange(
            previous_price=previous.price,
            current_price=current.price,
            difference=difference,
            percentage=percentage,
            is_price_drop=difference < 0,
            marketplace=current.marketplace,
            product_identifier=current.external_id,
            timestamp=current.collected_at,
        )
