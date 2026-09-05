from __future__ import annotations

from urllib.parse import urljoin

import httpx

from app.core.http_client import HttpClient


class FunPayFetchError(RuntimeError):
    """Raised when a raw FunPay response cannot be downloaded."""


class FunPayFetcher:
    """Downloads raw FunPay marketplace responses without parsing them."""

    CATALOG_URL = "https://funpay.com/"
    DEFAULT_URL = "https://funpay.com/en/lots/3486/"
    MAX_REDIRECTS = 3

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
        """Download and return the raw FunPay response body as text."""
        self.last_status_code = None
        self.last_content_type = None

        current_url = url
        for _ in range(self.MAX_REDIRECTS + 1):
            try:
                response = await self._http_client.get(
                    current_url,
                    headers=self.DEFAULT_HEADERS,
                )
            except httpx.RequestError as exc:
                msg = f"FunPay request failed: {type(exc).__name__}: {exc}"
                raise FunPayFetchError(msg) from exc

            self.last_status_code = response.status_code
            self.last_content_type = response.headers.get("content-type")

            if not 300 <= response.status_code < 400:
                break

            location = response.headers.get("location")
            if location is None:
                msg = f"FunPay returned HTTP {response.status_code} without Location"
                raise FunPayFetchError(msg)

            current_url = urljoin(current_url, location)
        else:
            msg = f"FunPay exceeded {self.MAX_REDIRECTS} redirects"
            raise FunPayFetchError(msg)

        if response.status_code >= 400:
            msg = f"FunPay returned HTTP {response.status_code}"
            raise FunPayFetchError(msg)

        if not response.text.strip():
            msg = "FunPay returned an empty response body"
            raise FunPayFetchError(msg)

        return response.text
