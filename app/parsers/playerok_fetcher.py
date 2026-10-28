from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from app.core.http_client import HttpClient
from app.parsers.playerok_credentials import PlayerokSessionCredentials

type JsonObject = dict[str, Any]


class PlayerokFailureKind(StrEnum):
    """Stable operational classifications for Playerok retrieval failures."""

    CONNECTION = "connection"
    SESSION_EXPIRED = "session_expired"
    BLOCKED = "blocked"
    RATE_LIMITED = "rate_limited"
    INVALID_RESPONSE = "invalid_response"
    HTTP_ERROR = "http_error"


class PlayerokFetchError(RuntimeError):
    """Safe base error raised when Playerok data cannot be downloaded."""

    kind = PlayerokFailureKind.HTTP_ERROR

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message)


class PlayerokConnectionError(PlayerokFetchError):
    """Playerok could not be reached through the configured transport."""

    kind = PlayerokFailureKind.CONNECTION


class PlayerokSessionExpiredError(PlayerokFetchError):
    """The configured Playerok browser session is no longer accepted."""

    kind = PlayerokFailureKind.SESSION_EXPIRED


class PlayerokAccessBlockedError(PlayerokFetchError):
    """Playerok access protection blocked the configured collector."""

    kind = PlayerokFailureKind.BLOCKED


class PlayerokRateLimitedError(PlayerokFetchError):
    """Playerok throttled the configured collector."""

    kind = PlayerokFailureKind.RATE_LIMITED


class PlayerokInvalidResponseError(PlayerokFetchError):
    """Playerok returned an unusable GraphQL response."""

    kind = PlayerokFailureKind.INVALID_RESPONSE


@dataclass(slots=True, frozen=True)
class _GraphQLParameters:
    first: int
    after: str | None
    game_id: str | None
    game_category_id: str | None


@dataclass(slots=True, frozen=True)
class _ItemsPage:
    payload: JsonObject
    edges: list[Any]
    has_next_page: bool
    end_cursor: str | None


class PlayerokFetcher:
    """Download Playerok responses with optional browser-session credentials."""

    GRAPHQL_URL = "https://playerok.com/graphql"
    HOMEPAGE_URL = "https://playerok.com/"
    DEFAULT_URL = GRAPHQL_URL
    DEFAULT_MAX_PAGES = 50

    ITEMS_QUERY = """
query items(
  $filter: ItemFilter,
  $pagination: Pagination,
  $sort: Sort,
  $showForbiddenImage: Boolean
) {
  items(filter: $filter, pagination: $pagination, sort: $sort) {
    edges {
      cursor
      node {
        ... on MyItemProfile {
          id
          slug
          name
          price
          rawPrice
          status
          user { id username }
          category { id name slug }
          game { id name slug }
          attachment(showForbiddenImage: $showForbiddenImage) { url }
        }
        ... on ForeignItemProfile {
          id
          slug
          name
          price
          rawPrice
          status
          user { id username }
          category { id name slug }
          game { id name slug }
          attachment(showForbiddenImage: $showForbiddenImage) { url }
        }
      }
    }
    pageInfo {
      startCursor
      endCursor
      hasPreviousPage
      hasNextPage
    }
    totalCount
  }
}
""".strip()

    DEFAULT_HEADERS = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
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
        session: PlayerokSessionCredentials | None = None,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> None:
        """Initialize shared transport, optional session, and pagination bound."""
        if max_pages < 1:
            raise ValueError("Playerok maximum page count must be positive.")
        self._http_client = http_client
        self._session = session
        self._max_pages = max_pages
        self.last_status_code: int | None = None
        self.last_content_type: str | None = None
        self.last_diagnostic: str | None = None
        self.pages_fetched = 0

    async def fetch(self, url: str = DEFAULT_URL) -> str:
        """Download a raw response, traversing all bounded GraphQL item pages."""
        self._reset_diagnostics()

        graphql_parameters = self._graphql_parameters(url)
        if graphql_parameters is not None:
            return await self.fetch_all_items(
                first=graphql_parameters.first,
                after=graphql_parameters.after,
                game_id=graphql_parameters.game_id,
                game_category_id=graphql_parameters.game_category_id,
            )

        try:
            response = await self._http_client.get(
                url,
                headers=self._request_headers(graphql=False),
            )
        except httpx.RequestError as exc:
            error = PlayerokConnectionError(
                f"Playerok request failed ({type(exc).__name__})."
            )
            self.last_diagnostic = str(error)
            raise error from exc

        return self._read_response(response)

    async def fetch_items(
        self,
        *,
        first: int = 20,
        after: str | None = None,
        game_id: str | None = None,
        game_category_id: str | None = None,
    ) -> str:
        """Download one optionally category-scoped Playerok item page."""
        self._reset_diagnostics()
        self._validate_page_size(first)
        return await self._fetch_items_page(
            first=first,
            after=after,
            game_id=game_id,
            game_category_id=game_category_id,
        )

    async def fetch_all_items(
        self,
        *,
        first: int = 20,
        after: str | None = None,
        game_id: str | None = None,
        game_category_id: str | None = None,
    ) -> str:
        """Traverse Playerok item cursors and return one merged GraphQL payload."""
        self._reset_diagnostics()
        self._validate_page_size(first)
        cursor = after
        seen_cursors = {after} if after is not None else set()
        first_payload: JsonObject | None = None
        merged_edges: list[Any] = []

        for page_number in range(1, self._max_pages + 1):
            raw = await self._fetch_items_page(
                first=first,
                after=cursor,
                game_id=game_id,
                game_category_id=game_category_id,
            )
            self.pages_fetched = page_number
            page = self._items_page(raw)
            if first_payload is None:
                first_payload = page.payload
            merged_edges.extend(page.edges)

            if not page.has_next_page:
                if page_number == 1:
                    return raw
                assert first_payload is not None
                self._replace_merged_items(
                    first_payload,
                    merged_edges=merged_edges,
                    final_page=page,
                )
                return json.dumps(
                    first_payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )

            next_cursor = page.end_cursor
            if next_cursor is None or next_cursor in seen_cursors:
                raise self._invalid_response(
                    "Playerok pagination returned a missing or repeated cursor."
                )
            seen_cursors.add(next_cursor)
            cursor = next_cursor

        raise self._invalid_response(
            "Playerok pagination exceeded the configured page limit."
        )

    def _graphql_parameters(self, url: str) -> _GraphQLParameters | None:
        configured = urlsplit(url)
        endpoint = urlsplit(self.GRAPHQL_URL)
        if (
            configured.scheme,
            configured.netloc,
            configured.path,
        ) != (endpoint.scheme, endpoint.netloc, endpoint.path):
            return None

        values = parse_qs(configured.query, keep_blank_values=True)
        allowed = {"first", "after", "game_id", "game_category_id"}
        unknown = set(values) - allowed
        if unknown:
            names = ", ".join(sorted(unknown))
            raise PlayerokFetchError(
                f"Unsupported Playerok GraphQL source parameters: {names}"
            )
        if any(len(items) != 1 for items in values.values()):
            raise PlayerokFetchError(
                "Playerok GraphQL source parameters must not be repeated"
            )

        first_value = _optional_parameter(values, "first")
        try:
            first = 20 if first_value is None else int(first_value)
        except ValueError as exc:
            raise PlayerokFetchError(
                "Playerok GraphQL first parameter must be an integer"
            ) from exc
        self._validate_page_size(first)

        return _GraphQLParameters(
            first=first,
            after=_optional_parameter(values, "after"),
            game_id=_optional_parameter(values, "game_id"),
            game_category_id=_optional_parameter(values, "game_category_id"),
        )

    async def _fetch_items_page(
        self,
        *,
        first: int,
        after: str | None,
        game_id: str | None,
        game_category_id: str | None,
    ) -> str:
        item_filter: dict[str, object] = {"status": ["APPROVED"]}
        if game_id is not None:
            item_filter["gameId"] = game_id
        if game_category_id is not None:
            item_filter["gameCategoryId"] = game_category_id

        payload = {
            "operationName": "items",
            "query": self.ITEMS_QUERY,
            "variables": {
                "filter": item_filter,
                "pagination": {"first": first, "after": after},
                "showForbiddenImage": True,
            },
        }
        try:
            response = await self._http_client.post(
                self.GRAPHQL_URL,
                json=payload,
                headers=self._request_headers(graphql=True),
            )
        except httpx.RequestError as exc:
            error = PlayerokConnectionError(
                f"Playerok request failed ({type(exc).__name__})."
            )
            self.last_diagnostic = str(error)
            raise error from exc
        return self._read_response(response)

    def _request_headers(self, *, graphql: bool) -> dict[str, str]:
        headers = dict(self.DEFAULT_HEADERS)
        if graphql:
            headers.update(
                {
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Origin": "https://playerok.com",
                    "Referer": "https://playerok.com/",
                }
            )
        if self._session is not None:
            headers["User-Agent"] = self._session.user_agent
            headers["Cookie"] = self._session.cookie_header()
        return headers

    def _read_response(self, response: httpx.Response) -> str:
        self.last_status_code = response.status_code
        self.last_content_type = response.headers.get("content-type")

        if response.status_code == 401:
            raise self._failure(
                PlayerokSessionExpiredError,
                "Playerok session is expired or unauthorized.",
                response,
            )
        if response.status_code == 403:
            raise self._failure(
                PlayerokAccessBlockedError,
                "Playerok collector was blocked by access protection.",
                response,
            )
        if response.status_code == 429:
            retry_after = _retry_after_seconds(response.headers.get("retry-after"))
            raise self._failure(
                PlayerokRateLimitedError,
                "Playerok rate limit was reached.",
                response,
                retry_after_seconds=retry_after,
            )
        if response.status_code >= 400:
            raise self._failure(
                PlayerokFetchError,
                f"Playerok returned HTTP {response.status_code}.",
                response,
            )
        if not response.text.strip():
            raise self._invalid_response("Playerok returned an empty response body")
        return response.text

    def _items_page(self, raw: str) -> _ItemsPage:
        if _looks_like_access_challenge(raw):
            error = PlayerokAccessBlockedError(
                "Playerok collector received an access-protection challenge.",
                status_code=self.last_status_code,
            )
            self.last_diagnostic = str(error)
            raise error
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise self._invalid_response(
                "Playerok GraphQL response is not valid JSON."
            ) from exc
        if not isinstance(payload, dict):
            raise self._invalid_response(
                "Playerok GraphQL response must contain an object."
            )
        if payload.get("errors"):
            raise self._invalid_response("Playerok GraphQL returned errors.")

        data = payload.get("data")
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, dict):
            raise self._invalid_response(
                "Playerok GraphQL response does not contain item data."
            )
        edges = items.get("edges")
        if not isinstance(edges, list):
            raise self._invalid_response(
                "Playerok GraphQL response does not contain item edges."
            )
        page_info = items.get("pageInfo")
        if not isinstance(page_info, dict):
            return _ItemsPage(payload, edges, False, None)
        has_next_page = page_info.get("hasNextPage") is True
        end_cursor = page_info.get("endCursor")
        return _ItemsPage(
            payload=payload,
            edges=edges,
            has_next_page=has_next_page,
            end_cursor=end_cursor if isinstance(end_cursor, str) else None,
        )

    def _replace_merged_items(
        self,
        payload: JsonObject,
        *,
        merged_edges: list[Any],
        final_page: _ItemsPage,
    ) -> None:
        data = payload["data"]
        assert isinstance(data, dict)
        items = data["items"]
        assert isinstance(items, dict)
        items["edges"] = merged_edges
        final_data = final_page.payload["data"]
        assert isinstance(final_data, dict)
        final_items = final_data["items"]
        assert isinstance(final_items, dict)
        if "pageInfo" in final_items:
            items["pageInfo"] = final_items["pageInfo"]

    def _validate_page_size(self, first: int) -> None:
        if not 1 <= first <= 100:
            raise PlayerokFetchError(
                "Playerok GraphQL first parameter must be between 1 and 100"
            )

    def _failure[ErrorT: PlayerokFetchError](
        self,
        error_type: type[ErrorT],
        message: str,
        response: httpx.Response,
        *,
        retry_after_seconds: int | None = None,
    ) -> ErrorT:
        error = error_type(
            message,
            status_code=response.status_code,
            retry_after_seconds=retry_after_seconds,
        )
        self.last_diagnostic = str(error)
        return error

    def _invalid_response(self, message: str) -> PlayerokInvalidResponseError:
        error = PlayerokInvalidResponseError(
            message,
            status_code=self.last_status_code,
        )
        self.last_diagnostic = str(error)
        return error

    def _reset_diagnostics(self) -> None:
        self.last_status_code = None
        self.last_content_type = None
        self.last_diagnostic = None
        self.pages_fetched = 0


def _optional_parameter(values: dict[str, list[str]], name: str) -> str | None:
    parameter = values.get(name)
    if parameter is None:
        return None
    value = parameter[0].strip()
    if not value:
        raise PlayerokFetchError(f"Playerok GraphQL {name} parameter must not be empty")
    return value


def _retry_after_seconds(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        seconds = int(value)
    except ValueError:
        return None
    return max(seconds, 0)


def _looks_like_access_challenge(raw: str) -> bool:
    normalized = raw[:20_000].lower()
    return any(
        marker in normalized
        for marker in (
            "ddos-guard",
            "checking your browser",
            "access denied",
            "captcha",
        )
    )
