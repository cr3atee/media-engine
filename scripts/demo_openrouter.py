from __future__ import annotations

import asyncio

from app.ai.openrouter_provider import OpenRouterProvider
from app.config.settings import settings


async def main() -> None:
    api_key = settings.openrouter.api_key
    if not api_key:
        print("OPENROUTER_API_KEY is not set. Add it to .env or environment.")
        return

    provider = OpenRouterProvider(api_key=api_key)
    try:
        result = await provider.generate_text(
            system_prompt="Ты профессиональный редактор Telegram-каналов.",
            user_prompt=(
                "Напиши короткий Telegram-пост о том, что Minecraft Premium "
                "подешевел с 990 ₽ до 790 ₽ на Playerok."
            ),
        )
    finally:
        await provider.aclose()

    print(result)


if __name__ == "__main__":
    asyncio.run(main())
