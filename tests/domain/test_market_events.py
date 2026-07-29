from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from app.domain.identity import canonicalize_decimal
from app.domain.lifecycle import EventDisposition, ScoringStatus
from app.domain.market_events import (
    CURRENT_EVENT_IDENTITY_VERSION,
    MarketEventType,
    PriceDropMarketEvent,
    PriceDropPayload,
    SnapshotIdentity,
    UnsupportedEventIdentityVersion,
    build_event_identity,
    create_price_drop_market_event,
)

EVENT_ID = UUID("00000000-0000-0000-0000-000000000013")
PRODUCT_ID = UUID("00000000-0000-0000-0000-000000000101")
PREVIOUS_AT = datetime(2026, 7, 29, 8, 0, tzinfo=UTC)
CURRENT_AT = datetime(2026, 7, 29, 8, 5, tzinfo=UTC)
DETECTED_AT = datetime(2026, 7, 29, 8, 6, tzinfo=UTC)
CREATED_AT = datetime(2026, 7, 29, 8, 7, tzinfo=UTC)


def make_snapshot(
    *,
    marketplace: str = "ggsel",
    external_id: str = "offer-1",
    collected_at: datetime = PREVIOUS_AT,
    price: Decimal = Decimal("990.00"),
    currency: str = "RUB",
) -> SnapshotIdentity:
    """Create one deterministic snapshot identity."""
    return SnapshotIdentity(
        marketplace=marketplace,
        external_id=external_id,
        collected_at=collected_at,
        price=price,
        currency=currency,
    )


def make_payload(
    *,
    title: str | None = "Minecraft Premium",
    url: str | None = "https://example.com/item/offer-1",
    previous_snapshot: SnapshotIdentity | None = None,
    current_snapshot: SnapshotIdentity | None = None,
) -> PriceDropPayload:
    """Create one deterministic typed price-drop payload."""
    previous = previous_snapshot or make_snapshot()
    current = current_snapshot or make_snapshot(
        collected_at=CURRENT_AT,
        price=Decimal("790.00"),
    )
    return PriceDropPayload(
        title=title,
        url=url,
        old_price=previous.price,
        new_price=current.price,
        currency=current.currency,
        absolute_difference=previous.price - current.price,
        percentage=Decimal("20.20202020202020202020202020"),
        previous_snapshot=previous,
        current_snapshot=current,
    )


def make_event(
    *,
    payload: PriceDropPayload | None = None,
    canonical_product_id: UUID | None = None,
) -> PriceDropMarketEvent:
    """Create one fully identified persistent market event."""
    return create_price_drop_market_event(
        payload=payload or make_payload(),
        detected_at=DETECTED_AT,
        event_id=EVENT_ID,
        canonical_product_id=canonical_product_id,
        created_at=CREATED_AT,
    )


def identity_for(
    previous: SnapshotIdentity,
    current: SnapshotIdentity,
    *,
    event_type: MarketEventType | str = MarketEventType.PRICE_DROP,
    marketplace: str = "ggsel",
    external_id: str = "offer-1",
    identity_version: int = CURRENT_EVENT_IDENTITY_VERSION,
) -> str:
    """Return an identity key for focused identity tests."""
    return build_event_identity(
        event_type=event_type,
        marketplace=marketplace,
        external_id=external_id,
        previous_snapshot=previous,
        current_snapshot=current,
        identity_version=identity_version,
    ).key


def test_identical_input_produces_identical_event_identity() -> None:
    previous = make_snapshot()
    current = make_snapshot(collected_at=CURRENT_AT, price=Decimal("790.00"))

    assert identity_for(previous, current) == identity_for(previous, current)


def test_identity_is_stable_across_snapshot_reconstruction() -> None:
    first_previous = make_snapshot(price=Decimal("990.0"))
    first_current = make_snapshot(
        collected_at=CURRENT_AT,
        price=Decimal("790.00"),
    )
    second_previous = make_snapshot(price=Decimal("990.000"))
    second_current = make_snapshot(
        collected_at=CURRENT_AT,
        price=Decimal("790.0"),
    )

    assert identity_for(first_previous, first_current) == identity_for(
        second_previous,
        second_current,
    )


def test_title_url_score_state_and_canonical_product_do_not_change_identity() -> None:
    event = make_event()
    changed_payload = replace(
        event.payload,
        title="Renamed product",
        url="https://example.com/renamed",
    )
    changed_presentation = make_event(
        payload=changed_payload,
        canonical_product_id=PRODUCT_ID,
    )
    scored = replace(
        event,
        disposition=EventDisposition.APPROVED,
        scoring_status=ScoringStatus.SUCCEEDED,
        score=80,
    )

    assert changed_presentation.identity_key == event.identity_key
    assert scored.identity_key == event.identity_key


@pytest.mark.parametrize("snapshot_name", ["previous", "current"])
def test_changing_either_snapshot_changes_identity(snapshot_name: str) -> None:
    previous = make_snapshot()
    current = make_snapshot(collected_at=CURRENT_AT, price=Decimal("790.00"))
    original = identity_for(previous, current)

    if snapshot_name == "previous":
        previous = replace(previous, price=Decimal("980.00"))
    else:
        current = replace(current, price=Decimal("780.00"))

    assert identity_for(previous, current) != original


def test_event_type_changes_identity_without_using_python_class_names() -> None:
    previous = make_snapshot()
    current = make_snapshot(collected_at=CURRENT_AT, price=Decimal("790.00"))

    assert identity_for(previous, current) != identity_for(
        previous,
        current,
        event_type="future_stable_type",
    )


def test_marketplace_change_changes_identity() -> None:
    previous = make_snapshot(marketplace="playerok")
    current = make_snapshot(
        marketplace="playerok",
        collected_at=CURRENT_AT,
        price=Decimal("790.00"),
    )

    changed = identity_for(previous, current, marketplace="playerok")

    assert changed != make_event().identity_key


def test_external_id_change_changes_identity() -> None:
    previous = make_snapshot(external_id="offer-2")
    current = make_snapshot(
        external_id="offer-2",
        collected_at=CURRENT_AT,
        price=Decimal("790.00"),
    )

    changed = identity_for(previous, current, external_id="offer-2")

    assert changed != make_event().identity_key


def test_currency_change_changes_identity() -> None:
    previous = make_snapshot(currency="USD")
    current = make_snapshot(
        collected_at=CURRENT_AT,
        price=Decimal("790.00"),
        currency="USD",
    )

    assert identity_for(previous, current) != make_event().identity_key


def test_timezone_equivalent_timestamps_have_identical_identity() -> None:
    plus_seven = timezone(timedelta(hours=7))
    previous_local = make_snapshot(
        collected_at=datetime(2026, 7, 29, 15, 0, tzinfo=plus_seven),
    )
    current_local = make_snapshot(
        collected_at=datetime(2026, 7, 29, 15, 5, tzinfo=plus_seven),
        price=Decimal("790.00"),
    )

    assert identity_for(previous_local, current_local) == make_event().identity_key


def test_different_snapshot_timestamp_changes_identity() -> None:
    previous = make_snapshot(collected_at=PREVIOUS_AT + timedelta(seconds=1))
    current = make_snapshot(collected_at=CURRENT_AT, price=Decimal("790.00"))

    assert identity_for(previous, current) != make_event().identity_key


def test_equivalent_decimal_scales_have_identical_canonical_value() -> None:
    assert canonicalize_decimal(Decimal("10.0")) == "10"
    assert canonicalize_decimal(Decimal("10.00")) == "10"


def test_unsupported_identity_version_fails_explicitly() -> None:
    previous = make_snapshot()
    current = make_snapshot(collected_at=CURRENT_AT, price=Decimal("790.00"))

    with pytest.raises(
        UnsupportedEventIdentityVersion,
        match="Unsupported event identity version: 2",
    ):
        identity_for(previous, current, identity_version=2)


def test_market_event_and_payload_are_immutable() -> None:
    event = make_event()

    with pytest.raises(FrozenInstanceError):
        event.marketplace = "playerok"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        event.payload.new_price = Decimal("700")  # type: ignore[misc]


def test_money_remains_decimal_and_payload_serialization_is_deterministic() -> None:
    event = make_event()

    assert isinstance(event.payload.old_price, Decimal)
    assert isinstance(event.payload.new_price, Decimal)
    assert isinstance(event.payload.absolute_difference, Decimal)
    assert isinstance(event.payload.percentage, Decimal)
    assert event.payload.to_dict()["old_price"] == "990"
    assert event.payload.to_dict()["new_price"] == "790"
    assert event.payload.to_dict() == event.payload.to_dict()


def test_event_serialization_is_stable_and_utc_aware() -> None:
    event = make_event()
    reconstructed = make_event(payload=make_payload())

    first = json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True)
    second = json.dumps(reconstructed.to_dict(), ensure_ascii=False, sort_keys=True)

    assert first == second
    assert event.occurred_at.tzinfo is UTC
    assert event.detected_at.tzinfo is UTC
    assert event.created_at.tzinfo is UTC


def test_naive_snapshot_timestamp_is_rejected() -> None:
    with pytest.raises(ValueError, match="collected_at must be timezone-aware"):
        make_snapshot(collected_at=datetime(2026, 7, 29, 8, 0))


def test_price_drop_payload_rejects_float_money() -> None:
    previous = make_snapshot()
    current = make_snapshot(collected_at=CURRENT_AT, price=Decimal("790.00"))

    with pytest.raises(TypeError, match="old_price must use Decimal"):
        PriceDropPayload(
            title="Minecraft Premium",
            url=None,
            old_price=990.0,  # type: ignore[arg-type]
            new_price=current.price,
            currency="RUB",
            absolute_difference=Decimal("200"),
            percentage=Decimal("20.2"),
            previous_snapshot=previous,
            current_snapshot=current,
        )
