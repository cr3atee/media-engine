from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


async def main() -> None:
    """Store and read price history through the PostgreSQL repository."""
    from app.database.session import SessionLocal, engine
    from app.domain.price_snapshot import PriceSnapshot
    from app.repositories.postgres import PostgresPriceHistoryRepository

    now = datetime.now(UTC)
    snapshots = (
        PriceSnapshot(
            marketplace="ggsel",
            external_id="minecraft-premium",
            price=Decimal("990.00"),
            currency="RUB",
            collected_at=now,
        ),
        PriceSnapshot(
            marketplace="ggsel",
            external_id="minecraft-premium",
            price=Decimal("890.00"),
            currency="RUB",
            collected_at=now + timedelta(minutes=5),
        ),
        PriceSnapshot(
            marketplace="ggsel",
            external_id="minecraft-premium",
            price=Decimal("790.00"),
            currency="RUB",
            collected_at=now + timedelta(minutes=10),
        ),
    )

    try:
        async with SessionLocal() as session:
            repository = PostgresPriceHistoryRepository(session)

            for snapshot in snapshots:
                await repository.add(snapshot)

            await session.commit()

            history = await repository.get_history("ggsel", "minecraft-premium")
            latest = await repository.get_last("ggsel", "minecraft-premium")
            previous = await repository.get_previous("ggsel", "minecraft-premium")

        print("PostgresPriceHistoryRepository history:")
        for snapshot in history:
            print(snapshot)
        print(f"Latest snapshot: {latest}")
        print(f"Previous snapshot: {previous}")
    except Exception as exc:
        print("PostgresPriceHistoryRepository demo failed")
        print(f"Reason: {exc}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
