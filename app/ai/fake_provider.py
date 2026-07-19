from __future__ import annotations

from app.ai.provider import AIProvider


class FakeAIProvider(AIProvider):
    """Test AI provider that builds deterministic text from a user prompt."""

    async def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """Generate a fake publication text without calling external APIs."""
        prompt_data = self._parse_user_prompt(user_prompt)
        title = prompt_data.get("Product title", "")
        marketplace = prompt_data.get("Marketplace", "")
        new_price = prompt_data.get("New price", "")
        discount = prompt_data.get("Discount", "")

        return (
            "Price drop\n\n"
            "A product price has decreased.\n\n"
            f"Product: {title}\n"
            f"Marketplace: {marketplace}\n"
            f"New price: {new_price}\n"
            f"Discount: {discount}"
        )

    def _parse_user_prompt(self, user_prompt: str) -> dict[str, str]:
        """Extract simple key-value pairs from a prompt."""
        result: dict[str, str] = {}
        for line in user_prompt.splitlines():
            key, separator, value = line.partition(":")
            if separator:
                result[key.strip()] = value.strip()
        return result
