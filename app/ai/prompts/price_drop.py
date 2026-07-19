from __future__ import annotations

from app.domain.events import PriceDropEvent


class PriceDropPromptBuilder:
    """Builds prompts for price drop publication generation."""

    def build(self, event: PriceDropEvent) -> tuple[str, str]:
        """Return system and user prompts based on a price drop event."""
        system_prompt = (
            "Write a Telegram post in Russian. Keep it short and professional. "
            "Avoid clickbait. Maximum length is 700 characters. Avoid emoji spam. "
            "Return only the final publication text."
        )
        user_prompt = (
            f"Product title: {event.title}\n"
            f"Marketplace: {event.marketplace}\n"
            f"Old price: {event.old_price:.2f} {event.currency}\n"
            f"New price: {event.new_price:.2f} {event.currency}\n"
            f"Discount: {event.discount_percent:.2f}%"
        )
        return system_prompt, user_prompt
