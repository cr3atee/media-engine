from __future__ import annotations

from app.domain.events import PriceDropEvent
from app.ai.prompts.templates import PRICE_DROP_SYSTEM_TEMPLATE


class PriceDropPromptBuilder:
    """Builds prompts for price drop publication generation."""

    def build(self, event: PriceDropEvent) -> tuple[str, str]:
        """Return system and user prompts based on a price drop event."""
        user_prompt = (
            f"Product title: {event.title}\n"
            f"Marketplace: {event.marketplace}\n"
            f"Old price: {event.old_price:.2f} {event.currency}\n"
            f"New price: {event.new_price:.2f} {event.currency}\n"
            f"Discount: {event.discount_percent:.2f}%"
        )
        return PRICE_DROP_SYSTEM_TEMPLATE, user_prompt
