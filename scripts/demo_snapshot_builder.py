from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.parsers.models import ParsedOffer
from app.services.snapshot_builder import SnapshotBuilder


def main() -> None:
    """Build and print a price snapshot from a parsed offer example."""
    offer = ParsedOffer(
        marketplace="ggsel",
        external_id="minecraft-premium",
        title="Minecraft Premium",
        url="https://ggsel.net/catalog/minecraft-premium",
        price=Decimal("790"),
        currency="RUB",
    )

    snapshot = SnapshotBuilder().build(offer)

    print("PriceSnapshot")
    print(f"Marketplace: {snapshot.marketplace}")
    print(f"External ID: {snapshot.external_id}")
    print(f"Price: {snapshot.price} {snapshot.currency}")
    print(f"Collected at: {snapshot.collected_at.isoformat()}")


if __name__ == "__main__":
    main()
