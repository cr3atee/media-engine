from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.domain.events import PriceDropEvent
from app.domain.market_events import MarketEventType, PriceDropMarketEvent
from app.services.event_processing_errors import PermanentEventProcessingError


class PriceDropScoringInput(PriceDropEvent):
    """Temporary legacy scoring DTO enriched with durable event context."""

    external_id: str
    url: str | None
    occurred_at: datetime
    detected_at: datetime
    discount_percentage: Decimal


class MarketEventScoringAdapter:
    """Adapt a durable market event to the current deterministic scorer input."""

    def adapt(self, event: PriceDropMarketEvent) -> PriceDropScoringInput:
        """Preserve durable facts while crossing the temporary float boundary."""
        if event.event_type is not MarketEventType.PRICE_DROP:
            msg = f"Unsupported market event type: {event.event_type.value}."
            raise PermanentEventProcessingError(msg)

        payload = event.payload
        if payload.new_price >= payload.old_price:
            msg = "Price-drop scoring input contains an impossible price direction."
            raise PermanentEventProcessingError(msg)

        return PriceDropScoringInput(
            title=payload.title or event.external_id,
            marketplace=event.marketplace,
            external_id=event.external_id,
            url=payload.url,
            old_price=float(payload.old_price),
            new_price=float(payload.new_price),
            currency=payload.currency,
            occurred_at=event.occurred_at,
            detected_at=event.detected_at,
            created_at=event.created_at,
            discount_percentage=payload.percentage,
        )
