from __future__ import annotations

from app.analytics.price_change_detector import PriceChangeDetector
from app.domain.events import PriceDropEvent
from app.domain.price_snapshot import PriceSnapshot


class PricePipeline:
    """Converts detected price drops into domain events."""

    def __init__(self, detector: PriceChangeDetector | None = None) -> None:
        """Initialize the pipeline with a price change detector."""
        self._detector = detector or PriceChangeDetector()

    def process(
        self,
        previous: PriceSnapshot,
        current: PriceSnapshot,
    ) -> PriceDropEvent | None:
        """Return a price drop event when the current price is lower."""
        price_change = self._detector.detect(previous, current)
        if price_change is None or not price_change.is_price_drop:
            return None

        return PriceDropEvent(
            title=current.external_id,
            marketplace=current.marketplace,
            old_price=float(price_change.previous_price),
            new_price=float(price_change.current_price),
            currency=current.currency,
        )
