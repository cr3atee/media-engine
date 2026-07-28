from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from app.analytics.price_change_detector import PriceChangeDetector
from app.domain.events import PriceDropEvent
from app.domain.price_snapshot import PriceSnapshot
from app.insights.scoring import EventScorer
from app.parsers.models import ParsedOffer
from app.repositories.provider import create_memory_provider
from app.services.price_pipeline import PricePipeline


async def main() -> None:
    marketplace = "ggsel"
    external_id = "minecraft-premium"
    currency = "RUB"
    offer = ParsedOffer(
        marketplace=marketplace,
        external_id=external_id,
        title="Minecraft Premium",
        url="https://ggsel.net/catalog/minecraft-premium",
        price=Decimal("990"),
        currency=currency,
    )
    first_snapshot = PriceSnapshot(
        marketplace=marketplace,
        external_id=external_id,
        price=Decimal("990"),
        currency=currency,
        collected_at=datetime.now(UTC),
    )
    second_snapshot = PriceSnapshot(
        marketplace=marketplace,
        external_id=external_id,
        price=Decimal("790"),
        currency=currency,
        collected_at=datetime.now(UTC),
    )

    history = create_memory_provider().price_history
    detector = PriceChangeDetector()
    pipeline = PricePipeline(detector)
    scorer = EventScorer()

    await history.add(first_snapshot)
    previous_snapshot = await history.get_last(marketplace, external_id)
    if previous_snapshot is None:
        return

    event = pipeline.process(previous_snapshot, second_snapshot)
    await history.add(second_snapshot)

    if isinstance(event, PriceDropEvent):
        score = scorer.score(event)
        print(f"Marketplace: {event.marketplace}")
        print(f"Title: {offer.title}")
        print(f"Old price: {event.old_price} {event.currency}")
        print(f"New price: {event.new_price} {event.currency}")
        print(f"Discount %: {event.discount_percent:.2f}")
        print(f"Score: {score}")


if __name__ == "__main__":
    asyncio.run(main())
