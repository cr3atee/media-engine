from __future__ import annotations

import httpx

from app.core.http_client import HttpClient


class PlayerokFetchError(RuntimeError):
    """Raised when a raw Playerok response cannot be downloaded."""


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

        if url == self.GRAPHQL_URL:
            return await self.fetch_items()

        try:
            response = await self._http_client.get(url, headers=self.DEFAULT_HEADERS)
        except httpx.RequestError as exc:
            msg = f"Playerok request failed: {type(exc).__name__}: {exc}"
            raise PlayerokFetchError(msg) from exc

        return self._read_response(response)

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
