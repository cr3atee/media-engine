from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.http_client import HttpClient
from app.parsers.ggsel_fetcher import GGSelFetcher, GGSelFetchError
from app.parsers.ggsel_parser import GGSelParser


async def main() -> None:
    """Fetch raw GGSEL data and print a compact diagnostic summary."""
    async with HttpClient() as http_client:
        fetcher = GGSelFetcher(http_client)
        try:
            raw_items = await fetcher.fetch(GGSelParser.CATALOG_URL)
        except GGSelFetchError as exc:
            print(f"Response status: {fetcher.last_status_code}")
            print(f"Diagnostic: {exc}")
            return

        print(f"Response status: {fetcher.last_status_code}")
        print(f"Raw items: {len(raw_items)}")
        print("First raw item structure:")
        if raw_items:
            print({key: type(value).__name__ for key, value in raw_items[0].items()})
        else:
            print("{}")


if __name__ == "__main__":
    asyncio.run(main())
