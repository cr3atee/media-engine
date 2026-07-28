from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


async def main() -> None:
    """Demonstrate comparator integration through the marketplace pipeline."""
    from app.ai.fake_provider import FakeAIProvider
    from app.analytics.price_change import PriceChangeDetector
    from app.comparator.result import ComparisonResult
    from app.core.http_client import HttpClient
    from app.insights.scoring import EventScorer
    from app.models.canonical_product import CanonicalProduct
    from app.parsers.ggsel_extractor import GGSelExtractor
    from app.parsers.ggsel_fetcher import GGSelFetcher
    from app.parsers.models import ParsedOffer
    from app.parsers.normalizers import OfferNormalizer
    from app.repositories.provider import create_memory_provider
    from app.services.content_generator import ContentGenerator
    from app.services.event_builder import EventBuilder
    from app.services.marketplace_pipeline import MarketplacePipeline
    from app.services.price_history import PriceHistoryService
    from app.services.snapshot_builder import SnapshotBuilder

    provider = create_memory_provider()
    canonical_id = uuid4()
    await provider.canonical_products.save(
        CanonicalProduct(
            id=canonical_id,
            name="Minecraft Premium",
            category=None,
            aliases=("minecraft",),
        ),
    )

    await provider.offers.save(
        ParsedOffer(
            marketplace="ggsel",
            external_id="ggsel-1",
            title="Minecraft Premium",
            url="https://ggsel.net/item/1",
            price=Decimal("990"),
            currency="RUB",
            seller_id=None,
            seller_name="GGSEL Seller",
            canonical_product_id=None,
        ),
    )
    await provider.offers.save(
        ParsedOffer(
            marketplace="playerok",
            external_id="playerok-1",
            title="Minecraft Premium",
            url="https://playerok.com/item/1",
            price=Decimal("790"),
            currency="RUB",
            seller_id=None,
            seller_name="Playerok Seller",
            canonical_product_id=None,
        ),
    )

    async with HttpClient() as http_client:
        pipeline = MarketplacePipeline(
            fetcher=GGSelFetcher(http_client),
            extractor=GGSelExtractor(),
            normalizer=OfferNormalizer(marketplace="ggsel"),
            repository_provider=provider,
            snapshot_builder=SnapshotBuilder(),
            price_history=PriceHistoryService(),
            price_change_detector=PriceChangeDetector(),
            event_builder=EventBuilder(),
            event_scorer=EventScorer(),
            content_generator=ContentGenerator(FakeAIProvider()),
        )

        comparison_results: list[ComparisonResult] = await pipeline.compare_offers(
            list(await provider.offers.list_all()),
        )

    for result in comparison_results:
        print("Canonical Product")
        if result.canonical_product is None:
            print("  <unmatched>")
        else:
            print(f"  {result.canonical_product.name}")
        print()

        print("Marketplace Offers")
        for offer in result.grouped_offers:
            parsed = offer.offer
            print(
                f"  - {parsed.marketplace}: {parsed.title} "
                f"{parsed.price} {parsed.currency}",
            )
        print()

        print("Best Offer")
        if result.best_offer is None:
            print("  None")
        else:
            best = result.best_offer.offer
            print(f"  {best.marketplace}: {best.title} {best.price} {best.currency}")
        print()

        print("Differences")
        if not result.comparison_entries:
            print("  None")
        else:
            for entry in result.comparison_entries:
                entry_offer = entry.offer.offer
                print(f"  - {entry_offer.marketplace}: {entry_offer.title}")
                print(f"    Absolute Difference: {entry.absolute_difference}")
                print(f"    Percentage Difference: {entry.percentage_difference}")
                if entry.reason is not None:
                    print(f"    Reason: {entry.reason}")
        print()

        print("Final Comparison Result")
        print(f"  Status: {result.status.value}")
        print(f"  Canonical Product ID: {result.canonical_product_id}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
