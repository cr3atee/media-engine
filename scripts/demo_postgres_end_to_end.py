from __future__ import annotations

import asyncio
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


async def main() -> None:
    """Verify the backend flow using PostgreSQL-backed repositories."""
    from app.ai.fake_provider import FakeAIProvider
    from app.analytics.price_change import PriceChangeDetector
    from app.comparator.difference import PriceDifferenceService
    from app.comparator.grouping import OfferGroupingService
    from app.comparator.models import MarketplaceOffer
    from app.comparator.result import ComparisonResultBuilder
    from app.comparator.selector import BestOfferSelector
    from app.database.session import SessionLocal, engine
    from app.domain.price_snapshot import PriceSnapshot
    from app.insights.scoring import EventScorer
    from app.matching.service import MatchingService
    from app.models.canonical_product import CanonicalProduct
    from app.parsers.models import ParsedOffer
    from app.repositories.provider import create_repository_provider
    from app.services.content_generator import ContentGenerator
    from app.services.event_builder import EventBuilder
    from app.services.snapshot_builder import SnapshotBuilder

    product = CanonicalProduct(
        id=uuid4(),
        name="Minecraft Premium",
        category="games",
        aliases=("minecraft", "mc premium"),
    )
    marketplace_offers = (
        ParsedOffer(
            marketplace="ggsel",
            external_id="ggsel-minecraft-premium",
            title="Minecraft Premium",
            url="https://example.com/ggsel/minecraft",
            price=Decimal("790.00"),
            currency="RUB",
            seller_id="ggsel-seller-1",
            seller_name="GGSEL Demo Seller",
            canonical_product_id=product.id,
        ),
        ParsedOffer(
            marketplace="playerok",
            external_id="playerok-minecraft-premium",
            title="Minecraft Premium",
            url="https://example.com/playerok/minecraft",
            price=Decimal("820.00"),
            currency="RUB",
            seller_id="playerok-seller-1",
            seller_name="Playerok Demo Seller",
            canonical_product_id=product.id,
        ),
    )

    try:
        print("=== Marketplace fetch ===")
        print("GGSEL marketplace output prepared.")
        print("Playerok marketplace output prepared.")

        async with SessionLocal() as session:
            provider = create_repository_provider("postgres", session)
            canonical_products = provider.canonical_products
            offers = provider.offers
            price_history = provider.price_history

            print("=== Offers parsed ===")
            for offer in marketplace_offers:
                print(offer)

            await canonical_products.save(product)
            for offer in marketplace_offers:
                await offers.save(offer)
            await session.commit()

            stored_products = await canonical_products.list_all()
            stored_offers = await offers.list_all()

            print("=== Offers persisted ===")
            print(f"Canonical products persisted: {len(stored_products)}")
            print(f"Offers persisted: {len(stored_offers)}")

            print("=== Matching ===")
            matching_service = MatchingService()
            for offer in stored_offers:
                match = matching_service.match(offer, stored_products)
                print(
                    f"{offer.marketplace}: {match.decision.value} "
                    f"similarity={match.similarity:.2f}"
                )

            print("=== Comparison ===")
            grouping = OfferGroupingService(matching_service=matching_service)
            selector = BestOfferSelector()
            difference_service = PriceDifferenceService()
            result_builder = ComparisonResultBuilder()
            grouped = grouping.group(
                [MarketplaceOffer(offer=offer) for offer in stored_offers],
                stored_products,
            )
            product_index = {item.id: item for item in stored_products}
            comparison_results = []
            for group in grouped:
                canonical_product = (
                    product_index.get(group.canonical_product_id)
                    if group.canonical_product_id is not None
                    else None
                )
                selection = selector.select(group)
                differences = difference_service.compare(selection)
                result = result_builder.build(
                    canonical_product,
                    selection,
                    differences,
                )
                comparison_results.append(result)
                print(result)

            print("=== Price history ===")
            snapshot_builder = SnapshotBuilder()
            current_snapshot = snapshot_builder.build(marketplace_offers[0])
            previous_snapshot = PriceSnapshot(
                marketplace=current_snapshot.marketplace,
                external_id=current_snapshot.external_id,
                price=Decimal("990.00"),
                currency=current_snapshot.currency,
                collected_at=current_snapshot.collected_at - timedelta(minutes=10),
            )
            await price_history.add(previous_snapshot)
            await price_history.add(current_snapshot)
            await session.commit()

            history = await price_history.get_history(
                current_snapshot.marketplace,
                current_snapshot.external_id,
            )
            latest = await price_history.get_last(
                current_snapshot.marketplace,
                current_snapshot.external_id,
            )
            previous = await price_history.get_previous(
                current_snapshot.marketplace,
                current_snapshot.external_id,
            )
            print(f"History size: {len(history)}")
            print(f"Previous: {previous}")
            print(f"Latest: {latest}")

        print("=== Price change ===")
        if previous is None or latest is None:
            msg = "Price history did not return comparable snapshots."
            raise RuntimeError(msg)
        price_change = PriceChangeDetector().detect(previous, latest)
        if price_change is None:
            msg = "Price change was not detected."
            raise RuntimeError(msg)
        print(price_change)

        print("=== Event ===")
        event = EventBuilder().build(price_change)
        if event is None:
            msg = "Price drop event was not built."
            raise RuntimeError(msg)
        print(event)

        print("=== Event score ===")
        score = EventScorer().score(event)
        print(score)

        print("=== Generated content ===")
        content = await ContentGenerator(FakeAIProvider()).generate(event)
        print(content)

        print("=== SUCCESS ===")
    except Exception as exc:
        print("=== FAILED ===")
        print(f"Reason: {exc}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
