from __future__ import annotations

import asyncio

from app.ai.fake_provider import FakeAIProvider
from app.ai.prompts.price_drop import PriceDropPromptBuilder
from app.domain.events import PriceDropEvent


async def main() -> None:
    event = PriceDropEvent(
        title="Minecraft Premium",
        marketplace="Playerok",
        old_price=990,
        new_price=790,
    )
    system_prompt, user_prompt = PriceDropPromptBuilder().build(event)
    result = await FakeAIProvider().generate_text(system_prompt, user_prompt)
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
