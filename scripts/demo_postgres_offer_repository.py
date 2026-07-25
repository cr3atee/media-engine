from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


async def main() -> None:
    """Save and read parsed offers through the PostgreSQL repository."""
    from app.database.session import SessionLocal, engine
    from app.parsers.models import ParsedOffer
    from app.repositories.postgres import PostgresOfferRepository

    offers = (
        ParsedOffer(
            marketplace="ggsel",
            external_id="ggsel-1",
            title="Minecraft Premium",
            url="https://example.com/ggsel/minecraft",
            price=Decimal("790.00"),
            currency="RUB",
            seller_id="seller-1",
            seller_name="Demo Seller",
        ),
        ParsedOffer(
            marketplace="playerok",
            external_id="playerok-1",
            title="Minecraft Premium",
            url="https://example.com/playerok/minecraft",
            price=Decimal("820.00"),
            currency="RUB",
            seller_id="seller-2",
            seller_name="Demo Playerok Seller",
        ),
    )

    try:
        async with SessionLocal() as session:
            repository = PostgresOfferRepository(session)

            for offer in offers:
                await repository.save(offer)

            await session.commit()

            saved_offers = await repository.list_all()

        print("PostgresOfferRepository contents:")
        for offer in saved_offers:
            print(offer)
    except Exception as exc:
        print("PostgresOfferRepository demo failed")
        print(f"Reason: {exc}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
