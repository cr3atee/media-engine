from __future__ import annotations

import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.analytics.price_change import PriceChangeDetector
from app.domain.price_snapshot import PriceSnapshot
from app.insights.scoring import EventScorer
from app.services.event_builder import EventBuilder


def main() -> None:
    """Demonstrate building a price drop event from a price change."""
    previous = PriceSnapshot(
        marketplace="ggsel",
        external_id="Minecraft Premium",
        price=Decimal("990"),
        currency="RUB",
        collected_at=datetime.now(UTC),
    )
    current = PriceSnapshot(
        marketplace="ggsel",
        external_id="Minecraft Premium",
        price=Decimal("790"),
        currency="RUB",
        collected_at=datetime.now(UTC),
    )

    change = PriceChangeDetector().detect(previous, current)
    if change is None:
        print("Price did not change.")
        return

    event = EventBuilder().build(change)
    if event is None:
        print("PriceDropEvent was not created.")
        return

    score = EventScorer().score(event)

    print("PriceDropEvent")
    print(f"Title: {event.title}")
    print(f"Marketplace: {event.marketplace}")
    print(f"Old price: {event.old_price} {event.currency}")
    print(f"New price: {event.new_price} {event.currency}")
    print(f"Discount: {event.discount_percent:.2f}%")
    print(f"Score: {score}")


if __name__ == "__main__":
    main()
