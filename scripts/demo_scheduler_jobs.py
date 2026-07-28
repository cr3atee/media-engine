from __future__ import annotations

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


async def main() -> None:
    """Demonstrate scheduler execution of job objects."""
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
    from app.services.snapshot_builder import SnapshotBuilder

    scheduler = SchedulerService()
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

        ggsel_job = GGSELJob(ggsel_pipeline)
        playerok_job = PlayerokJob(playerok_pipeline)

        print("Start scheduler")
        scheduler.start()

        print("Register GGSELJob")
        scheduler.register_job(ggsel_job)

        print("Register PlayerokJob")
        scheduler.register_job(playerok_job)

        print("Execute jobs")
        await scheduler.execute_job(ggsel_job.name)
        await scheduler.execute_job(playerok_job.name)

        print("Print execution status")
        for job_name in (ggsel_job.name, playerok_job.name):
            status = scheduler.get_status(job_name)
            print(f"Job name: {status.name}")
            print(f"Started: {status.last_started_at}")
            print(f"Finished: {status.last_finished_at}")
            print(f"Duration: {status.last_duration}")
            print(f"Status: {status.state.value}")

        print("Stop scheduler")
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
