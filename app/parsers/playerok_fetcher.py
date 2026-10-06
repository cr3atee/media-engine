from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

import httpx

from app.core.http_client import HttpClient


class PlayerokFetchError(RuntimeError):
    """Raised when a raw Playerok response cannot be downloaded."""


@dataclass(slots=True, frozen=True)
class _GraphQLParameters:
    first: int
    after: str | None
    game_id: str | None
    game_category_id: str | None


class PlayerokFetcher:
    """Downloads raw Playerok marketplace responses without parsing them."""

    GRAPHQL_URL = "https://playerok.com/graphql"
    HOMEPAGE_URL = "https://playerok.com/"
    DEFAULT_URL = GRAPHQL_URL

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

    def __init__(self, http_client: HttpClient) -> None:
        """Initialize the fetcher with the shared HTTP client infrastructure."""
        self._http_client = http_client
        self.last_status_code: int | None = None
        self.last_content_type: str | None = None
        self.last_diagnostic: str | None = None

    async def fetch(self, url: str = DEFAULT_URL) -> str:
        """Download and return the raw Playerok response body as text."""
        self.last_status_code = None
        self.last_content_type = None
        self.last_diagnostic = None

        graphql_parameters = self._graphql_parameters(url)
        if graphql_parameters is not None:
            return await self.fetch_items(
                first=graphql_parameters.first,
                after=graphql_parameters.after,
                game_id=graphql_parameters.game_id,
                game_category_id=graphql_parameters.game_category_id,
            )

        try:
            response = await self._http_client.get(url, headers=self.DEFAULT_HEADERS)
        except httpx.RequestError as exc:
            msg = f"Playerok request failed: {type(exc).__name__}: {exc}"
            raise PlayerokFetchError(msg) from exc

        return self._read_response(response)

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
        if not 1 <= first <= 100:
            raise PlayerokFetchError(
                "Playerok GraphQL first parameter must be between 1 and 100"
            )

        return _GraphQLParameters(
            first=first,
            after=_optional_parameter(values, "after"),
            game_id=_optional_parameter(values, "game_id"),
            game_category_id=_optional_parameter(values, "game_category_id"),
        )

    async def fetch_items(
        self,
        *,
        first: int = 20,
        after: str | None = None,
        game_id: str | None = None,
        game_category_id: str | None = None,
    ) -> str:
        """Download optionally category-scoped Playerok item-list data."""
        item_filter: dict[str, object] = {"status": ["APPROVED"]}
        if game_id is not None:
            item_filter["gameId"] = game_id
        if game_category_id is not None:
            item_filter["gameCategoryId"] = game_category_id

        variables: dict[str, object] = {
            "filter": item_filter,
            "pagination": {"first": first, "after": after},
            "showForbiddenImage": True,
        }
        payload = {
            "operationName": "items",
            "query": self.ITEMS_QUERY,
            "variables": variables,
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://playerok.com",
            "Referer": "https://playerok.com/",
            "User-Agent": self.DEFAULT_HEADERS["User-Agent"],
        }

        try:
            response = await self._http_client.post(
                self.GRAPHQL_URL,
                json=payload,
                headers=headers,
            )
        except httpx.RequestError as exc:
            msg = f"Playerok request failed: {type(exc).__name__}: {exc}"
            raise PlayerokFetchError(msg) from exc

        return self._read_response(response)

    def _read_response(self, response: httpx.Response) -> str:
        """Validate transport-level response details and return raw text."""
        self.last_status_code = response.status_code
        self.last_content_type = response.headers.get("content-type")

        if response.status_code >= 400:
            response_snippet = " ".join(response.text[:300].split())
            msg = f"Playerok returned HTTP {response.status_code}: {response_snippet}"
            self.last_diagnostic = msg
            raise PlayerokFetchError(msg)

        if not response.text.strip():
            msg = "Playerok returned an empty response body"
            self.last_diagnostic = msg
            raise PlayerokFetchError(msg)

        return response.text


def _optional_parameter(values: dict[str, list[str]], name: str) -> str | None:
    parameter = values.get(name)
    if parameter is None:
        return None
    value = parameter[0].strip()
    if not value:
        raise PlayerokFetchError(f"Playerok GraphQL {name} parameter must not be empty")
    return value
