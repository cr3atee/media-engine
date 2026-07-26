from __future__ import annotations

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


async def main() -> None:
    """Demonstrate periodic scheduler execution for marketplace jobs."""
    from app.ai.fake_provider import FakeAIProvider
    from app.analytics.price_change import PriceChangeDetector
    from app.core.http_client import HttpClient
    from app.insights.scoring import EventScorer
    from app.parsers.ggsel_extractor import GGSelExtractor
    from app.parsers.ggsel_fetcher import GGSelFetcher
    from app.parsers.normalizers import OfferNormalizer
    from app.parsers.playerok_extractor import PlayerokExtractor
    from app.parsers.playerok_fetcher import PlayerokFetcher
    from app.parsers.playerok_normalizer import PlayerokNormalizer
    from app.repositories.provider import create_memory_provider
    from app.scheduler import GGSELJob, PlayerokJob, SchedulerService
    from app.services.content_generator import ContentGenerator
    from app.services.event_builder import EventBuilder
    from app.services.marketplace_pipeline import MarketplacePipeline
    from app.services.playerok_pipeline import PlayerokPipeline
    from app.services.price_history import PriceHistoryService
    from app.services.snapshot_builder import SnapshotBuilder

    scheduler = SchedulerService(tick_seconds=0.1)
    repository_provider = create_memory_provider()

    async with (
        HttpClient(timeout=1.0, max_retries=1) as ggsel_http_client,
        HttpClient(timeout=1.0, max_retries=1) as playerok_http_client,
    ):
        ggsel_pipeline = MarketplacePipeline(
            fetcher=GGSelFetcher(ggsel_http_client),
            extractor=GGSelExtractor(),
            normalizer=OfferNormalizer(),
            repository_provider=repository_provider,
            snapshot_builder=SnapshotBuilder(),
            price_history=PriceHistoryService(),
            price_change_detector=PriceChangeDetector(),
            event_builder=EventBuilder(),
            event_scorer=EventScorer(),
            content_generator=ContentGenerator(FakeAIProvider()),
        )
        playerok_pipeline = PlayerokPipeline(
            fetcher=PlayerokFetcher(playerok_http_client),
            extractor=PlayerokExtractor(),
            normalizer=PlayerokNormalizer(),
        )

        print("Start Scheduler")
        scheduler.start()

        print("Register GGSELJob")
        scheduler.register_job(GGSELJob(ggsel_pipeline), interval_seconds=1)

        print("Register PlayerokJob")
        scheduler.register_job(PlayerokJob(playerok_pipeline), interval_seconds=2)

        print("Run scheduler for a short period")
        for tick in range(4):
            await asyncio.sleep(1)
            print(f"Timeline tick: {tick + 1}")
            for status in scheduler.list_statuses():
                schedule = scheduler.get_schedule_status(status.name)
                print(
                    f"{status.name}: runs={status.run_count}, "
                    f"status={status.state.value}, "
                    f"last={schedule.last_execution_time}, "
                    f"next={schedule.next_scheduled_run}"
                )

        print("Gracefully stop scheduler")
        await scheduler.stop()


if __name__ == "__main__":
    asyncio.run(main())
