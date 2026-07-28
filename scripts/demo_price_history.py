from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

async def main() -> None:
    """Demonstrate in-memory price history lookup for two snapshots."""
    from app.domain.price_snapshot import PriceSnapshot
    from app.repositories.provider import create_memory_provider

    history = create_memory_provider().price_history
    marketplace = "ggsel"
    external_id = "Minecraft Premium"

    first_snapshot = PriceSnapshot(
        marketplace=marketplace,
        external_id=external_id,
        price=Decimal("990"),
        currency="RUB",
        collected_at=datetime.now(UTC),
    )
    await history.add(first_snapshot)

    second_snapshot = PriceSnapshot(
        marketplace=marketplace,
        external_id=external_id,
        price=Decimal("790"),
        currency="RUB",
        collected_at=datetime.now(UTC),
    )
    await history.add(second_snapshot)

    previous_snapshot = await history.get_previous(marketplace, external_id)

    print("Price history")
    print(f"Marketplace: {marketplace}")
    print(f"Product: {external_id}")
    print(f"Current price: {second_snapshot.price} {second_snapshot.currency}")
    if previous_snapshot is None:
        print("Previous price: not found")
        return

    print(f"Previous price: {previous_snapshot.price} {previous_snapshot.currency}")


if __name__ == "__main__":
    asyncio.run(main())
