from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

HTML_RESPONSE_PATH = PROJECT_ROOT / "tmp" / "ggsel_response.html"


async def main() -> None:
    """Run the complete GGSEL vertical slice and print each domain result."""
    from app.ai.fake_provider import FakeAIProvider
    from app.analytics.price_change import PriceChangeDetector
    from app.parsers.ggsel_extractor import GGSelExtractor
    from app.parsers.normalizers import OfferNormalizer
    from app.repositories.provider import create_memory_provider
    from app.services.content_generator import ContentGenerator
    from app.services.event_builder import EventBuilder
    from app.services.snapshot_builder import SnapshotBuilder

    if not HTML_RESPONSE_PATH.exists():
        print(f"GGSEL response is unavailable: {HTML_RESPONSE_PATH}")
        return

    raw_response = HTML_RESPONSE_PATH.read_text(encoding="utf-8")
    raw_offers = GGSelExtractor().extract(raw_response)
    if not raw_offers:
        print("GGSEL response contains no extractable offers.")
        return

    parsed_offer = OfferNormalizer(marketplace="ggsel").normalize(raw_offers[0])
    current_snapshot = SnapshotBuilder().build(parsed_offer)
    previous_snapshot = replace(
        current_snapshot,
        price=current_snapshot.price + Decimal("10"),
        collected_at=current_snapshot.collected_at - timedelta(minutes=1),
    )

    price_history = create_memory_provider().price_history
    await price_history.add(previous_snapshot)
    await price_history.add(current_snapshot)

    previous = await price_history.get_previous(
        current_snapshot.marketplace,
        current_snapshot.external_id,
    )
    current = await price_history.get_last(
        current_snapshot.marketplace,
        current_snapshot.external_id,
    )
    if previous is None or current is None:
        print("GGSEL price history does not contain two snapshots.")
        return

    price_change = PriceChangeDetector().detect(previous, current)
    if price_change is None:
        print("GGSEL price did not change.")
        return

    event = EventBuilder().build(price_change)
    if event is None:
        print("GGSEL price change did not produce an event.")
        return

    generated_content = await ContentGenerator(FakeAIProvider()).generate(event)

    print("=== ParsedOffer ===")
    print(f"Marketplace: {parsed_offer.marketplace}")
    print(f"External ID: {parsed_offer.external_id}")
    print(f"Title: {parsed_offer.title}")
    print(f"Price: {parsed_offer.price} {parsed_offer.currency}")
    print(f"URL: {parsed_offer.url}")
    print()

    print("=== Snapshot ===")
    print(current_snapshot)
    print()

    print("=== PriceChange ===")
    print(price_change)
    print()

    print("=== Event ===")
    print(event.model_dump())
    print()

    print("=== Generated content ===")
    print(generated_content)


if __name__ == "__main__":
    asyncio.run(main())
