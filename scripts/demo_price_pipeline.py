from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from app.analytics.price_change_detector import PriceChangeDetector
from app.domain.events import PriceDropEvent
from app.domain.price_snapshot import PriceSnapshot
from app.insights.scoring import EventScorer
from app.parsers.models import ParsedOffer
from app.services.price_history import PriceHistoryService
from app.services.price_pipeline import PricePipeline


async def main() -> None:
    offer = ParsedOffer(
        marketplace="ggsel",
        external_id="minecraft-premium",
        title="Minecraft Premium",
        url="https://ggsel.net/catalog/minecraft-premium",
        price=Decimal("990"),
        currency="RUB",
    )
    first_snapshot = PriceSnapshot(
        marketplace=offer.marketplace,
        external_id=offer.external_id,
        price=offer.price,
        currency=offer.currency,
        collected_at=datetime.now(UTC),
    )
    second_snapshot = PriceSnapshot(
        marketplace=offer.marketplace,
        external_id=offer.external_id,
        price=Decimal("790"),
        currency=offer.currency,
        collected_at=datetime.now(UTC),
    )

    history = PriceHistoryService()
    detector = PriceChangeDetector()
    pipeline = PricePipeline(detector)
    scorer = EventScorer()

    history.add(first_snapshot)
    previous_snapshot = history.get_last(offer.marketplace, offer.external_id)
    if previous_snapshot is None:
        return

    event = pipeline.process(previous_snapshot, second_snapshot)
    history.add(second_snapshot)

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
