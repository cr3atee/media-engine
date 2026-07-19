from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from app.ai.fake_provider import FakeAIProvider
from app.domain.events import PriceDropEvent
from app.services.content_generator import ContentGenerator


async def main() -> None:
    """Generate demo content for a price drop event."""
    event = PriceDropEvent(
        title="Minecraft Premium",
        marketplace="Playerok",
        old_price=990,
        new_price=790,
        currency="RUB",
    )
    generator = ContentGenerator(ai_provider=FakeAIProvider())
    text = await generator.generate(event)
    print(text)


if __name__ == "__main__":
    asyncio.run(main())
