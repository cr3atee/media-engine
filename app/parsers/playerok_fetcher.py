from __future__ import annotations

import httpx

from app.core.http_client import HttpClient


class PlayerokFetchError(RuntimeError):
    """Raised when a raw Playerok response cannot be downloaded."""


class PlayerokFetcher:
    """Downloads raw Playerok marketplace responses without parsing them."""

    DEFAULT_URL = "https://playerok.com/"

    DEFAULT_HEADERS = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
    }

    def __init__(self, http_client: HttpClient) -> None:
        """Initialize the fetcher with the shared HTTP client infrastructure."""
        self._http_client = http_client
        self.last_status_code: int | None = None
        self.last_content_type: str | None = None

    async def fetch(self, url: str = DEFAULT_URL) -> str:
        """Download and return the raw Playerok response body as text."""
        self.last_status_code = None
        self.last_content_type = None

        try:
            response = await self._http_client.get(url, headers=self.DEFAULT_HEADERS)
        except httpx.RequestError as exc:
            msg = f"Playerok request failed: {exc}"
            raise PlayerokFetchError(msg) from exc

        self.last_status_code = response.status_code
        self.last_content_type = response.headers.get("content-type")

        if response.status_code >= 400:
            msg = f"Playerok returned HTTP {response.status_code}"
            raise PlayerokFetchError(msg)

        return response.text
