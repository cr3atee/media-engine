from __future__ import annotations

from datetime import datetime

from app.analytics.models import PriceChange
from app.domain.events import PriceDropEvent
from app.domain.identity import normalize_utc
from app.domain.market_events import (
    PriceDropMarketEvent,
    PriceDropPayload,
    SnapshotIdentity,
    create_price_drop_market_event,
)
from app.domain.price_snapshot import PriceSnapshot
from app.parsers.models import ParsedOffer


class PriceDropMarketEventBuilder:
    """Build durable price-drop events and temporary runtime DTOs."""

    def build(
        self,
        *,
        offer: ParsedOffer,
        previous_snapshot: PriceSnapshot,
        current_snapshot: PriceSnapshot,
        change: PriceChange,
        detected_at: datetime,
    ) -> PriceDropMarketEvent:
        """Build one immutable event from an exact persisted transition."""
        detected_at = normalize_utc(detected_at, field_name="detected_at")
        self._validate_inputs(
            offer=offer,
            previous_snapshot=previous_snapshot,
            current_snapshot=current_snapshot,
            change=change,
        )
        payload = PriceDropPayload(
            title=offer.title,
            url=offer.url,
            old_price=change.previous_price,
            new_price=change.current_price,
            currency=current_snapshot.currency,
            absolute_difference=change.absolute_difference,
            percentage=abs(change.percentage),
            previous_snapshot=SnapshotIdentity.from_snapshot(previous_snapshot),
            current_snapshot=SnapshotIdentity.from_snapshot(current_snapshot),
        )
        return create_price_drop_market_event(
            payload=payload,
            detected_at=detected_at,
            canonical_product_id=offer.canonical_product_id,
            created_at=detected_at,
        )

    @staticmethod
    def to_runtime_event(event: PriceDropMarketEvent) -> PriceDropEvent:
        """Adapt a durable event to the current scoring/content DTO."""
        return PriceDropEvent(
            title=event.payload.title or event.external_id,
            marketplace=event.marketplace,
            old_price=float(event.payload.old_price),
            new_price=float(event.payload.new_price),
            currency=event.payload.currency,
            created_at=event.created_at,
        )

    @staticmethod
    def _validate_inputs(
        *,
        offer: ParsedOffer,
        previous_snapshot: PriceSnapshot,
        current_snapshot: PriceSnapshot,
        change: PriceChange,
    ) -> None:
        if not change.is_price_drop:
            msg = "Persistent price-drop events require a decreasing price change."
            raise ValueError(msg)
        if offer.external_id is None:
            msg = "Persistent market events require an external offer ID."
            raise ValueError(msg)
        expected_identity = (offer.marketplace, offer.external_id)
        if (
            previous_snapshot.marketplace,
            previous_snapshot.external_id,
        ) != expected_identity or (
            current_snapshot.marketplace,
            current_snapshot.external_id,
        ) != expected_identity:
            msg = "Offer and snapshot identities must match."
            raise ValueError(msg)
        if (
            change.marketplace != current_snapshot.marketplace
            or change.product_identifier != current_snapshot.external_id
        ):
            msg = "Price-change identity must match the current snapshot."
            raise ValueError(msg)
        if (
            change.previous_price != previous_snapshot.price
            or change.current_price != current_snapshot.price
        ):
            msg = "Price-change values must match the exact snapshots."
            raise ValueError(msg)
        if change.timestamp != current_snapshot.collected_at:
            msg = "Price-change timestamp must match the current snapshot."
            raise ValueError(msg)
