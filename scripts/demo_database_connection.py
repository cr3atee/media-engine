from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import text

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


async def main() -> None:
    """Open an async PostgreSQL session and execute a health query."""
    from app.database.session import SessionLocal, engine

    try:
        async with SessionLocal() as session:
            result = await session.execute(text("SELECT 1"))
            value = result.scalar_one()

        print("PostgreSQL connection: ok")
        print(f"Health query result: {value}")
    except Exception as exc:
        print("PostgreSQL connection: failed")
        print(f"Reason: {exc}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
