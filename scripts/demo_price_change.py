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


def main() -> None:
    """Demonstrate price change detection between two snapshots."""
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

    price_change = PriceChangeDetector().detect(previous, current)
    if price_change is None:
        print("Price did not change.")
        return

    print(f"Old price: {price_change.old_price} {previous.currency}")
    print(f"New price: {price_change.new_price} {current.currency}")
    print(f"Difference: {price_change.absolute_difference} {current.currency}")
    print(f"Percentage: {price_change.percentage_difference}%")


if __name__ == "__main__":
    main()
