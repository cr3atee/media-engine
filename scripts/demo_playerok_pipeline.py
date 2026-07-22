from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.http_client import HttpClient
from app.parsers.playerok_extractor import PlayerokExtractor
from app.parsers.playerok_fetcher import PlayerokFetchError, PlayerokFetcher
from app.parsers.playerok_normalizer import PlayerokNormalizer
from app.services.playerok_pipeline import PlayerokPipeline


async def main() -> None:
    """Run the Playerok pipeline and print its real extraction result."""
    try:
        async with HttpClient() as http_client:
            pipeline = PlayerokPipeline(
                fetcher=PlayerokFetcher(http_client),
                extractor=PlayerokExtractor(),
                normalizer=PlayerokNormalizer(),
            )
            offers = await pipeline.run()
    except PlayerokFetchError as exc:
        print(f"Playerok pipeline failed: {exc}")
        return

    print(f"Parsed offers: {len(offers)}")
    if offers:
        print(f"First offer: {offers[0]}")
    else:
        print("First offer: unavailable; no offers were extracted.")


if __name__ == "__main__":
    asyncio.run(main())
