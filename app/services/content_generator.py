from __future__ import annotations

from app.ai.prompts.price_drop import PriceDropPromptBuilder
from app.ai.provider import AIProvider
from app.domain.events import PriceDropEvent


class ContentGenerator:
    """Generates publication text for price drop events."""

    def __init__(
        self,
        ai_provider: AIProvider,
        prompt_builder: PriceDropPromptBuilder | None = None,
    ) -> None:
        """Initialize the generator with an AI provider and prompt builder."""
        self._ai_provider = ai_provider
        self._prompt_builder = prompt_builder or PriceDropPromptBuilder()

    async def generate(self, event: PriceDropEvent) -> str:
        """Generate final publication text for a price drop event."""
        system_prompt, user_prompt = self._prompt_builder.build(event)
        return await self._ai_provider.generate_text(system_prompt, user_prompt)
