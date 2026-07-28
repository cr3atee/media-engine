# ruff: noqa: E402, I001
from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ai.fake_provider import FakeAIProvider
from app.analytics.price_change import PriceChangeDetector
from app.comparator.result import ComparisonResult
from app.domain.price_snapshot import PriceSnapshot
from app.insights.scoring import EventScorer
from app.models.canonical_product import CanonicalProduct
from app.parsers.ggsel_extractor import GGSelExtractor
from app.parsers.ggsel_fetcher import GGSelFetcher
from app.parsers.models import ParsedOffer, RawMarketplaceOffer
from app.parsers.normalizers import OfferNormalizer
from app.parsers.playerok_extractor import PlayerokExtractor
from app.parsers.playerok_fetcher import PlayerokFetcher
from app.parsers.playerok_normalizer import PlayerokNormalizer
from app.repositories.provider import RepositoryProvider, create_memory_provider
from app.scheduler.jobs import GGSELJob, PlayerokJob
from app.scheduler.service import SchedulerService
from app.services.content_generator import ContentGenerator
from app.services.event_builder import EventBuilder
from app.services.marketplace_pipeline import MarketplacePipeline
from app.services.playerok_pipeline import PlayerokPipeline
from app.services.price_history import PriceHistoryService
from app.services.snapshot_builder import SnapshotBuilder


class DemoGGSelFetcher:
    """Provides deterministic GGSEL input for scheduler verification."""

    async def fetch_html(self, url: str) -> str:
        """Return a minimal raw response consumed by the demo extractor."""
        return "<html><script>window.__MEDIAENGINE_DEMO__ = true;</script></html>"


class DemoGGSelExtractor:
    """Returns typed GGSEL raw offers without external network access."""

    def extract(self, html: str) -> list[RawMarketplaceOffer]:
        """Return a single raw GGSEL marketplace offer."""
        return [
            RawMarketplaceOffer(
                id_goods=1001,
                name="Minecraft Premium",
                url="https://ggsel.net/catalog/minecraft-premium",
                seller_name="GGSEL Seller",
                id_section=10,
                price=790.0,
                currency="RUB",
                extra={"seller_id": "ggsel-seller-1"},
            ),
        ]


class DemoPlayerokFetcher:
    """Provides deterministic Playerok input for scheduler verification."""

    async def fetch(self, url: str) -> str:
        """Return a raw JSON response compatible with PlayerokExtractor."""
        return json.dumps(
            {
                "items": [
                    {
                        "id": "playerok-1001",
                        "slug": "minecraft-premium",
                        "title": "Minecraft Premium",
                        "url": "https://playerok.com/products/minecraft-premium",
                        "price": {"amount": "820.00", "currency": "RUB"},
                        "seller": {
                            "id": "playerok-seller-1",
                            "username": "Playerok Seller",
                        },
                    },
                ],
            },
        )


def _print_section(title: str) -> None:
    print(f"\n=== {title} ===")


async def _seed_canonical_products(provider: RepositoryProvider) -> None:
    await provider.canonical_products.save(
        CanonicalProduct(
            id=uuid4(),
            name="Minecraft Premium",
            category="games",
            aliases=("minecraft", "premium"),
        ),
    )


def _seed_price_history(price_history: PriceHistoryService) -> None:
    price_history.add(
        PriceSnapshot(
            marketplace="ggsel",
            external_id="1001",
            price=Decimal("990.00"),
            currency="RUB",
            collected_at=datetime.now(UTC) - timedelta(minutes=10),
        ),
    )


def _build_ggsel_pipeline(
    provider: RepositoryProvider,
    price_history: PriceHistoryService,
) -> MarketplacePipeline:
    return MarketplacePipeline(
        fetcher=cast(GGSelFetcher, DemoGGSelFetcher()),
        extractor=cast(GGSelExtractor, DemoGGSelExtractor()),
        normalizer=OfferNormalizer("ggsel"),
        repository_provider=provider,
        snapshot_builder=SnapshotBuilder(),
        price_history=price_history,
        price_change_detector=PriceChangeDetector(),
        event_builder=EventBuilder(),
        event_scorer=EventScorer(),
        content_generator=ContentGenerator(FakeAIProvider()),
        stage_reporter=lambda message: print(f"[GGSEL] {message}"),
    )


def _build_playerok_pipeline(
    comparison_pipeline: MarketplacePipeline,
) -> PlayerokPipeline:
    return PlayerokPipeline(
        fetcher=cast(PlayerokFetcher, DemoPlayerokFetcher()),
        extractor=PlayerokExtractor(),
        normalizer=PlayerokNormalizer(),
        comparison_pipeline=comparison_pipeline,
    )


async def _print_repository_activity(provider: RepositoryProvider) -> None:
    offers = await provider.offers.list_all()
    products = await provider.canonical_products.list_all()
    print(f"Stored offers: {len(offers)}")
    print(f"Canonical products: {len(products)}")
    for offer in offers:
        print(
            f"- {offer.marketplace}: {offer.title} | "
            f"{offer.price} {offer.currency} | {offer.url}",
        )


def _print_comparator_activity(results: list[ComparisonResult]) -> None:
    print(f"Comparison results: {len(results)}")
    for result in results:
        product_name = (
            result.canonical_product.name
            if result.canonical_product is not None
            else "unmatched"
        )
        best = result.best_offer.offer if result.best_offer is not None else None
        print(f"Canonical Product: {product_name}")
        print(f"Status: {result.status.value}")
        if best is not None:
            print(f"Best Offer: {best.marketplace} {best.price} {best.currency}")
        for entry in result.comparison_entries:
            offer = entry.offer.offer
            print(
                f"Difference: {offer.marketplace} "
                f"absolute={entry.absolute_difference} "
                f"percentage={entry.percentage_difference} "
                f"reason={entry.reason}",
            )


async def _persist_playerok_offers(
    provider: RepositoryProvider,
    pipeline: PlayerokPipeline,
) -> list[ParsedOffer]:
    offers = await pipeline.run("demo://playerok")
    for offer in offers:
        await provider.offers.save(offer)
    return offers


async def main() -> None:
    provider = create_memory_provider()
    price_history = PriceHistoryService()
    await _seed_canonical_products(provider)
    _seed_price_history(price_history)

    ggsel_pipeline = _build_ggsel_pipeline(provider, price_history)
    playerok_pipeline = _build_playerok_pipeline(ggsel_pipeline)

    scheduler = SchedulerService()
    ggsel_job = GGSELJob(ggsel_pipeline, url="demo://ggsel")
    playerok_job = PlayerokJob(playerok_pipeline, url="demo://playerok")

    _print_section("Scheduler started")
    scheduler.start()

    _print_section("Jobs registered")
    scheduler.register_job(ggsel_job)
    scheduler.register_job(playerok_job)
    for status in scheduler.list_statuses():
        print(f"{status.name}: {status.state.value}")

    _print_section("GGSEL execution")
    await scheduler.execute_job(ggsel_job.name)
    print(scheduler.get_status(ggsel_job.name))

    _print_section("Playerok execution")
    await scheduler.execute_job(playerok_job.name)
    print(scheduler.get_status(playerok_job.name))

    _print_section("Repository activity")
    playerok_offers = await _persist_playerok_offers(provider, playerok_pipeline)
    print(
        "Playerok offers persisted after scheduled execution: "
        f"{len(playerok_offers)}",
    )
    await _print_repository_activity(provider)

    _print_section("Comparator activity")
    comparison_results = await ggsel_pipeline.compare_repository_offers()
    _print_comparator_activity(comparison_results)

    _print_section("Price history update")
    history = price_history.get_history("ggsel", "1001")
    print(f"GGSEL history entries: {len(history)}")
    for snapshot in history:
        print(f"- {snapshot.marketplace}:{snapshot.external_id} {snapshot.price}")

    _print_section("Price change detection")
    previous = price_history.get_previous("ggsel", "1001")
    current = price_history.get_last("ggsel", "1001")
    if previous is None or current is None:
        print("Price change unavailable.")
        change = None
    else:
        change = PriceChangeDetector().detect(previous, current)
        print(change)

    _print_section("Event creation")
    event = EventBuilder().build(change) if change is not None else None
    print(event if event is not None else "No event created.")

    _print_section("Content generation")
    if event is None:
        print("No content generated.")
    else:
        score = EventScorer().score(event)
        content = await ContentGenerator(FakeAIProvider()).generate(event)
        print(f"Score: {score}")
        print(content)

    _print_section("Scheduler statistics")
    for statistics in scheduler.list_statistics():
        print(statistics)

    _print_section("Scheduler shutdown")
    await scheduler.stop()
    print("Scheduler stopped")

    _print_section("SUCCESS")
    print("Scheduler end-to-end verification completed.")


if __name__ == "__main__":
    asyncio.run(main())
