from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

async def main() -> None:
    """Run the complete demo workflow from parsed offer to generated content."""
    from app.ai.fake_provider import FakeAIProvider
    from app.analytics.price_change import PriceChangeDetector
    from app.insights.scoring import EventScorer
    from app.parsers.models import ParsedOffer
    from app.repositories.provider import create_memory_provider
    from app.services.content_generator import ContentGenerator
    from app.services.event_builder import EventBuilder
    from app.services.snapshot_builder import SnapshotBuilder

    previous_offer = ParsedOffer(
        marketplace="Playerok",
        external_id="Minecraft Premium",
        title="Minecraft Premium",
        url="https://example.com/product",
        price=Decimal("990"),
        currency="RUB",
    )
    current_offer = ParsedOffer(
        marketplace="Playerok",
        external_id="Minecraft Premium",
        title="Minecraft Premium",
        url="https://example.com/product",
        price=Decimal("790"),
        currency="RUB",
    )

    snapshot_builder = SnapshotBuilder()
    price_history = create_memory_provider().price_history
    price_change_detector = PriceChangeDetector()
    event_builder = EventBuilder()
    event_scorer = EventScorer()
    content_generator = ContentGenerator(ai_provider=FakeAIProvider())

    previous_snapshot = snapshot_builder.build(previous_offer)
    await price_history.add(previous_snapshot)

    current_snapshot = snapshot_builder.build(current_offer)
    stored_previous_snapshot = await price_history.get_last(
        current_snapshot.marketplace,
        current_snapshot.external_id,
    )
    if stored_previous_snapshot is None:
        print("Previous snapshot was not found.")
        return

    await price_history.add(current_snapshot)
    price_change = price_change_detector.detect(
        stored_previous_snapshot,
        current_snapshot,
    )

    print("=== OFFER ===")
    print(f"Product: {current_offer.title}")
    print(f"Marketplace: {current_offer.marketplace}")
    print(f"Old price: {previous_offer.price} {previous_offer.currency}")
    print(f"New price: {current_offer.price} {current_offer.currency}")
    print(f"URL: {current_offer.url}")
    print()

    print("=== SNAPSHOT ===")
    print(f"Marketplace: {current_snapshot.marketplace}")
    print(f"External ID: {current_snapshot.external_id}")
    print(f"Price: {current_snapshot.price} {current_snapshot.currency}")
    print(f"Collected at: {current_snapshot.collected_at.isoformat()}")
    print()

    print("=== PRICE CHANGE ===")
    if price_change is None:
        print("Price did not change.")
        return
    print(f"Old price: {price_change.old_price}")
    print(f"New price: {price_change.new_price}")
    print(f"Difference: {price_change.difference}")
    print(f"Percentage: {price_change.percentage:.2f}%")
    print()

    print("=== EVENT ===")
    event = event_builder.build(price_change)
    if event is None:
        print("PriceDropEvent was not created.")
        return
    print(f"Type: {event.event_type}")
    print(f"Title: {event.title}")
    print(f"Marketplace: {event.marketplace}")
    print(f"Old price: {event.old_price} {event.currency}")
    print(f"New price: {event.new_price} {event.currency}")
    print(f"Discount: {event.discount_percent:.2f}%")
    print()

    print("=== SCORE ===")
    print(event_scorer.score(event))
    print()

    print("=== GENERATED POST ===")
    print(await content_generator.generate(event))


if __name__ == "__main__":
    asyncio.run(main())
