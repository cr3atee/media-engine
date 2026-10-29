from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeGuard
from urllib.parse import unquote, urlsplit

import httpx

from app.core.http_client import HttpClient
from app.parsers.source_snapshot import SourceExtraction, SourceSnapshotEvidence

type RawOfferData = dict[str, object]


@dataclass(slots=True, frozen=True)
class _CategorySource:
    slug: str
    language: str
    currency: str


class GGSelFetchError(RuntimeError):
    """Raised when GGSEL raw data cannot be fetched or interpreted safely."""


class GGSelFetcher:
    """Fetches raw GGSEL data without converting it into domain objects."""

    CATEGORY_API_URL = "https://api.ggsel.com/buybox/goods"
    CATEGORY_PAGE_SIZE = 60
    DEFAULT_MAX_PAGES = 50
    CATEGORY_HEADERS = {
        "Accept": "application/json",
        "Origin": "https://ggsel.net",
        "Referer": "https://ggsel.net/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
    }

    def __init__(
        self,
        http_client: HttpClient,
        *,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> None:
        """Initialize fetcher with the shared HTTP client infrastructure."""
        if max_pages < 1:
            raise ValueError("GGSEL maximum page count must be positive.")
        self._http_client = http_client
        self._max_pages = max_pages
        self.last_status_code: int | None = None
        self.last_diagnostic: str | None = None
        self.pages_fetched = 0

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
            self.last_diagnostic = (
                "JSON response does not contain raw dictionary items."
            )
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

    async def fetch_complete_category(
        self,
        url: str,
    ) -> SourceExtraction[RawOfferData]:
        """Traverse the public GGSEL category API and prove full coverage."""
        self.last_status_code = None
        self.last_diagnostic = None
        self.pages_fetched = 0
        source = self._category_source(url)
        items: list[RawOfferData] = []
        seen_ids: set[str] = set()
        expected_items: int | None = None

        for page in range(1, self._max_pages + 1):
            try:
                response = await self._http_client.get(
                    self.CATEGORY_API_URL,
                    params={
                        "url": source.slug,
                        "lang": source.language,
                        "limit": self.CATEGORY_PAGE_SIZE,
                        "page": page,
                        "sort": "sortByRec",
                        "currency": source.currency,
                    },
                    headers=self.CATEGORY_HEADERS,
                )
            except httpx.RequestError as exc:
                error = self._error(f"Connection error: {type(exc).__name__}.")
                raise error from exc

            self.pages_fetched = page
            page_items, page_total = self._read_category_page(response)
            if expected_items is None:
                expected_items = page_total
            elif page_total != expected_items:
                raise self._error("GGSEL category total changed during pagination.")

            for item in page_items:
                item_id = self._item_id(item)
                if item_id is None:
                    raise self._error(
                        "GGSEL category item has no stable product identifier."
                    )
                if item_id in seen_ids:
                    raise self._error(
                        "GGSEL category pagination returned a duplicate product."
                    )
                seen_ids.add(item_id)
                items.append(item)

            assert expected_items is not None
            if len(items) > expected_items:
                raise self._error(
                    "GGSEL category returned more products than declared."
                )
            if len(items) == expected_items:
                return SourceExtraction(
                    items=tuple(items),
                    evidence=SourceSnapshotEvidence(
                        source_items=len(items),
                        parsed_items=len(items),
                        expected_items=expected_items,
                        complete=True,
                        reason=(
                            "GGSEL pagination covered all "
                            f"{expected_items} declared products."
                        ),
                    ),
                )
            if not page_items:
                raise self._error(
                    "GGSEL category pagination ended before its declared total."
                )

        raise self._error(
            "GGSEL category pagination exceeded the configured page limit."
        )

    def _category_source(self, url: str) -> _CategorySource:
        parsed = urlsplit(url)
        host = parsed.hostname.lower() if parsed.hostname is not None else ""
        if parsed.scheme != "https" or host not in {"ggsel.net", "www.ggsel.net"}:
            raise self._error("GGSEL category source URL is unsupported.")

        segments = [unquote(segment) for segment in parsed.path.split("/") if segment]
        language = "ru"
        if segments[:1] == ["en"]:
            language = "en"
            segments = segments[1:]
        if len(segments) != 2 or segments[0] != "catalog" or not segments[1]:
            raise self._error("GGSEL category source URL is unsupported.")
        return _CategorySource(
            slug=segments[1],
            language=language,
            currency="wmz" if language == "en" else "wmr",
        )

    def _read_category_page(
        self,
        response: httpx.Response,
    ) -> tuple[list[RawOfferData], int]:
        self.last_status_code = response.status_code
        if response.status_code >= 400:
            raise self._error(
                f"Invalid GGSEL category response status: {response.status_code}"
            )
        if not response.content:
            raise self._error("GGSEL category returned an empty response body.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise self._error("GGSEL category response is not valid JSON.") from exc
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise self._error("GGSEL category response has an invalid envelope.")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise self._error("GGSEL category response has no product data.")
        raw_items = data.get("items")
        total = data.get("total")
        if not isinstance(raw_items, list):
            raise self._error("GGSEL category response has no product list.")
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise self._error("GGSEL category response has an invalid total.")
        items = [item for item in raw_items if self._is_raw_item(item)]
        if len(items) != len(raw_items):
            raise self._error("GGSEL category response contains invalid products.")
        if len(items) > self.CATEGORY_PAGE_SIZE:
            raise self._error("GGSEL category page exceeds the requested limit.")
        return items, total

    def _item_id(self, item: RawOfferData) -> str | None:
        value = item.get("id_goods")
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str) and value.isdigit():
            return value
        return None

    def _error(self, message: str) -> GGSelFetchError:
        self.last_diagnostic = message
        return GGSelFetchError(message)

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
        return isinstance(value, dict) and all(isinstance(key, str) for key in value)
