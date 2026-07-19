from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from app.ai.prompts.price_drop import PriceDropPromptBuilder
from app.domain.events import PriceDropEvent


def main() -> None:
    """Build and print the final prompt sent to an AI provider."""
    event = PriceDropEvent(
        title="Minecraft Premium",
        marketplace="Playerok",
        old_price=990,
        new_price=790,
        currency="RUB",
    )
    system_prompt, user_prompt = PriceDropPromptBuilder().build(event)

    print("System Prompt:")
    print(system_prompt)
    print()
    print("User Prompt:")
    print(user_prompt)


if __name__ == "__main__":
    main()
