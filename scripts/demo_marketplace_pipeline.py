from __future__ import annotations

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
from app.services.content_generator import ContentGenerator
from app.services.event_builder import EventBuilder
from app.services.marketplace_pipeline import MarketplacePipeline
from app.services.price_history import PriceHistoryService
from app.services.snapshot_builder import SnapshotBuilder

GGSEL_CATALOG_URL = "https://ggsel.net/catalog"


async def main() -> None:
    """Run the first real marketplace processing pipeline demo."""
    async with HttpClient() as http_client:
        pipeline = MarketplacePipeline(
            fetcher=GGSelFetcher(http_client),
            extractor=GGSelExtractor(),
            normalizer=OfferNormalizer(marketplace="ggsel"),
            snapshot_builder=SnapshotBuilder(),
            price_history=PriceHistoryService(),
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
