from __future__ import annotations

import os
from typing import Any

import httpx

from app.ai.exceptions import AIProviderError
from app.ai.provider import AIProvider


class OpenRouterProvider(AIProvider):
    """AI provider implementation for OpenRouter chat completions."""

    endpoint = "https://openrouter.ai/api/v1/chat/completions"
    model = "openai/gpt-5"

    def __init__(self, *, api_key: str | None = None) -> None:
        """Initialize the provider with one async HTTP client per instance."""
        self._api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        self._client = httpx.AsyncClient()

    async def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """Generate text using OpenRouter Chat Completions."""
        response = await self._client.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )

        if response.is_error:
            raise AIProviderError(response.text)

        data: dict[str, Any] = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError("Invalid OpenRouter response") from exc

        if not isinstance(content, str):
            raise AIProviderError("Invalid OpenRouter response content")

        return content

    async def aclose(self) -> None:
        """Close the underlying async HTTP client."""
        await self._client.aclose()
