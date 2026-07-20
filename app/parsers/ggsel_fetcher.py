from __future__ import annotations

from typing import Any, TypeAlias, TypeGuard

import httpx

from app.core.http_client import HttpClient

RawOfferData: TypeAlias = dict[str, object]


class GGSelFetchError(RuntimeError):
    """Raised when GGSEL raw data cannot be fetched or interpreted safely."""


class GGSelFetcher:
    """Fetches raw GGSEL data without converting it into domain objects."""

    def __init__(self, http_client: HttpClient) -> None:
        """Initialize fetcher with the shared HTTP client infrastructure."""
        self._http_client = http_client
        self.last_status_code: int | None = None
        self.last_diagnostic: str | None = None

    async def fetch(self, url: str) -> list[RawOfferData]:
        """Return raw dictionary items from a GGSEL JSON-compatible endpoint."""
        self.last_status_code = None
        self.last_diagnostic = None

        try:
            response = await self._http_client.get(url)
        except httpx.RequestError as exc:
            self.last_diagnostic = f"Connection error: {exc}"
            raise GGSelFetchError(self.last_diagnostic) from exc

        self.last_status_code = response.status_code
        if response.status_code >= 400:
            self.last_diagnostic = f"Invalid response status: {response.status_code}"
            raise GGSelFetchError(self.last_diagnostic)

        if not response.content:
            self.last_diagnostic = "Empty response body."
            raise GGSelFetchError(self.last_diagnostic)

        try:
            payload = response.json()
        except ValueError as exc:
            self.last_diagnostic = (
                "Response is not JSON. HTML parsing is intentionally not implemented."
            )
            raise GGSelFetchError(self.last_diagnostic) from exc

        items = self._extract_raw_items(payload)
        if not items:
            self.last_diagnostic = "JSON response does not contain raw dictionary items."
            raise GGSelFetchError(self.last_diagnostic)

        return items

    async def fetch_html(self, url: str) -> str:
        """Return raw HTML from GGSEL without extracting marketplace fields."""
        self.last_status_code = None
        self.last_diagnostic = None

        try:
            response = await self._http_client.get(url)
        except httpx.RequestError as exc:
            self.last_diagnostic = f"Connection error: {exc}"
            raise GGSelFetchError(self.last_diagnostic) from exc

        self.last_status_code = response.status_code
        if response.status_code >= 400:
            self.last_diagnostic = f"Invalid response status: {response.status_code}"
            raise GGSelFetchError(self.last_diagnostic)

        if not response.content:
            self.last_diagnostic = "Empty response body."
            raise GGSelFetchError(self.last_diagnostic)

        return response.text

    def _extract_raw_items(self, payload: Any) -> list[RawOfferData]:
        if isinstance(payload, list):
            return [item for item in payload if self._is_raw_item(item)]
        if isinstance(payload, dict):
            for value in payload.values():
                if isinstance(value, list):
                    items = [item for item in value if self._is_raw_item(item)]
                    if items:
                        return items
            if self._is_raw_item(payload):
                return [payload]
        return []

    def _is_raw_item(self, value: object) -> TypeGuard[RawOfferData]:
        return isinstance(value, dict) and all(
            isinstance(key, str) for key in value
        )
