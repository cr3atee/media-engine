from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.analytics.price_change import PriceChangeDetector
from app.domain.market_events import (
    PriceDropMarketEvent,
    PriceDropPayload,
    build_event_identity,
)
from app.domain.price_snapshot import PriceSnapshot
from app.parsers.models import ParsedOffer
from app.services.price_drop_market_event_builder import PriceDropMarketEventBuilder

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def make_offer(
    *,
    title: str = "Minecraft Premium",
    url: str = "https://example.com/minecraft",
    canonical_product_id: UUID | None = None,
) -> ParsedOffer:
    """Create deterministic offer context for builder tests."""
    return ParsedOffer(
        marketplace="ggsel",
        external_id="offer-1",
        title=title,
        url=url,
        price=Decimal("790.00"),
        currency="RUB",
        canonical_product_id=canonical_product_id,
    )


def make_snapshots() -> tuple[PriceSnapshot, PriceSnapshot]:
    """Create one exact deterministic price-drop transition."""
    return (
        PriceSnapshot(
            marketplace="ggsel",
            external_id="offer-1",
            price=Decimal("990.00"),
            currency="RUB",
            collected_at=NOW - timedelta(minutes=1),
        ),
        PriceSnapshot(
            marketplace="ggsel",
            external_id="offer-1",
            price=Decimal("790.00"),
            currency="RUB",
            collected_at=NOW,
        ),
    )


def build_event(offer: ParsedOffer | None = None) -> PriceDropMarketEvent:
    """Build a durable event through the active detector."""
    previous, current = make_snapshots()
    change = PriceChangeDetector().detect(previous, current)
    assert change is not None
    return PriceDropMarketEventBuilder().build(
        offer=offer or make_offer(),
        previous_snapshot=previous,
        current_snapshot=current,
        change=change,
        detected_at=current.collected_at,
    )


def test_builder_creates_typed_immutable_event_with_decimal_and_utc() -> None:
    event = build_event()

    assert isinstance(event.payload, PriceDropPayload)
    assert event.payload.old_price == Decimal("990.00")
    assert event.payload.new_price == Decimal("790.00")
    assert event.payload.absolute_difference == Decimal("200.00")
    assert event.payload.percentage == Decimal("20.20202020202020202020202020")
    assert event.detected_at == NOW
    assert event.detected_at.tzinfo is UTC
    with pytest.raises(FrozenInstanceError):
        event.version = 2  # type: ignore[misc]


def test_builder_uses_existing_identity_service() -> None:
    event = build_event()
    expected = build_event_identity(
        event_type=event.event_type,
        marketplace=event.marketplace,
        external_id=event.external_id,
        previous_snapshot=event.previous_snapshot,
        current_snapshot=event.current_snapshot,
    )

    assert event.identity_key == expected.key
    assert event.identity_version == expected.version


def test_title_url_and_canonical_product_do_not_change_identity() -> None:
    first = build_event()
    second = build_event(
        make_offer(
            title="Updated title",
            url="https://example.com/updated",
            canonical_product_id=uuid4(),
        )
    )

    assert first.identity_key == second.identity_key
    assert first.payload.title != second.payload.title
    assert first.canonical_product_id != second.canonical_product_id


def test_snapshot_change_changes_identity() -> None:
    first = build_event()
    previous, current = make_snapshots()
    shifted_previous = replace(
        previous,
        collected_at=previous.collected_at - timedelta(seconds=1),
    )
    change = PriceChangeDetector().detect(shifted_previous, current)
    assert change is not None
    second = PriceDropMarketEventBuilder().build(
        offer=make_offer(),
        previous_snapshot=shifted_previous,
        current_snapshot=current,
        change=change,
        detected_at=current.collected_at,
    )

    assert first.identity_key != second.identity_key


def test_runtime_adapter_preserves_current_scoring_content_values() -> None:
    event = build_event()
    runtime = PriceDropMarketEventBuilder.to_runtime_event(event)

    assert runtime.title == "Minecraft Premium"
    assert runtime.marketplace == "ggsel"
    assert runtime.old_price == 990.0
    assert runtime.new_price == 790.0
    assert runtime.currency == "RUB"
    assert runtime.created_at == event.created_at


def test_builder_rejects_non_utc_detection_time() -> None:
    previous, current = make_snapshots()
    change = PriceChangeDetector().detect(previous, current)
    assert change is not None

    with pytest.raises(ValueError, match="timezone-aware"):
        PriceDropMarketEventBuilder().build(
            offer=make_offer(),
            previous_snapshot=previous,
            current_snapshot=current,
            change=change,
            detected_at=NOW.replace(tzinfo=None),
        )
