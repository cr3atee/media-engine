from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


async def main() -> None:
    """Save and read canonical products through the PostgreSQL repository."""
    from app.database.session import SessionLocal, engine
    from app.models.canonical_product import CanonicalProduct
    from app.repositories.postgres import PostgresCanonicalProductRepository

    products = (
        CanonicalProduct(
            id=uuid4(),
            name="Minecraft Premium",
            category="games",
            aliases=("minecraft", "mc premium"),
        ),
        CanonicalProduct(
            id=uuid4(),
            name="Counter Strike 2",
            category="games",
            aliases=("cs2", "counter strike"),
        ),
    )

    try:
        async with SessionLocal() as session:
            repository = PostgresCanonicalProductRepository(session)

            for product in products:
                await repository.save(product)

            await session.commit()

            saved_products = await repository.list_all()

        print("PostgresCanonicalProductRepository contents:")
        for product in saved_products:
            print(product)
    except Exception as exc:
        print("PostgresCanonicalProductRepository demo failed")
        print(f"Reason: {exc}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
