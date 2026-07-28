from __future__ import annotations

# ruff: noqa: E402, I001

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.ai.fake_provider import FakeAIProvider
from app.analytics.price_change import PriceChangeDetector
from app.core.http_client import HttpClient
from app.insights.scoring import EventScorer
from app.parsers.ggsel_extractor import GGSelExtractor
from app.parsers.ggsel_fetcher import GGSelFetcher, GGSelFetchError
from app.parsers.normalizers import OfferNormalizer
from app.repositories.provider import create_memory_provider
from app.services.content_generator import ContentGenerator
from app.services.event_builder import EventBuilder
from app.services.marketplace_pipeline import MarketplacePipeline
from app.services.snapshot_builder import SnapshotBuilder

GGSEL_CATALOG_URL = "https://ggsel.net/catalog"


async def main() -> None:
    """Run the first real marketplace processing pipeline demo."""
    provider = create_memory_provider()

    async with HttpClient() as http_client:
        pipeline = MarketplacePipeline(
            fetcher=GGSelFetcher(http_client),
            extractor=GGSelExtractor(),
            normalizer=OfferNormalizer(marketplace="ggsel"),
            repository_provider=provider,
            snapshot_builder=SnapshotBuilder(),
            price_change_detector=PriceChangeDetector(),
            event_builder=EventBuilder(),
            event_scorer=EventScorer(),
            content_generator=ContentGenerator(ai_provider=FakeAIProvider()),
            stage_reporter=print,
        )

        try:
            await pipeline.run(GGSEL_CATALOG_URL)
        except GGSelFetchError as exc:
            print("=== FETCH ERROR ===")
            print(exc)


if __name__ == "__main__":
    asyncio.run(main())
