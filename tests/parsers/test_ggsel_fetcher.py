from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, cast

import httpx
import pytest

from app.core.http_client import HttpClient
from app.parsers.ggsel_fetcher import GGSelFetcher, GGSelFetchError

CATEGORY_URL = "https://ggsel.net/en/catalog/minecraft-keys-pc"


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run one async fetcher check without an external plugin."""
    return asyncio.run(awaitable)


def product(item_id: int) -> dict[str, object]:
    """Build one raw GGSEL API product."""
    return {
        "id_goods": item_id,
        "name": f"Product {item_id}",
        "url": f"product-{item_id}",
        "seller_name": "Seller",
        "id_section": 10,
        "price_wmr": "790",
    }


def page(items: list[dict[str, object]], *, total: int) -> httpx.Response:
    """Build one successful GGSEL category page."""
    return httpx.Response(
        200,
        json={"success": True, "data": {"items": items, "total": total}},
    )


def test_fetcher_traverses_complete_category() -> None:
    """GGSEL pagination returns one complete identity-checked snapshot."""
    client = _QueueHttpClient(
        [
            page([product(1), product(2)], total=3),
            page([product(3)], total=3),
        ]
    )
    fetcher = GGSelFetcher(cast(HttpClient, client), max_pages=3)

    extraction = run_async(fetcher.fetch_complete_category(CATEGORY_URL))

    assert [item["id_goods"] for item in extraction.items] == [1, 2, 3]
    assert extraction.evidence.complete is True
    assert extraction.evidence.expected_items == 3
    assert fetcher.pages_fetched == 2
    assert client.gets[0]["url"] == GGSelFetcher.CATEGORY_API_URL
    assert client.gets[0]["params"] == {
        "url": "minecraft-keys-pc",
        "lang": "en",
        "limit": 60,
        "page": 1,
        "sort": "sortByRec",
        "currency": "wmz",
    }
    assert client.gets[1]["params"]["page"] == 2


def test_fetcher_rejects_duplicate_products_across_pages() -> None:
    """A moving GGSEL listing cannot masquerade as complete coverage."""
    client = _QueueHttpClient(
        [
            page([product(1)], total=2),
            page([product(1)], total=2),
        ]
    )
    fetcher = GGSelFetcher(cast(HttpClient, client), max_pages=2)

    with pytest.raises(GGSelFetchError, match="duplicate product"):
        run_async(fetcher.fetch_complete_category(CATEGORY_URL))


def test_fetcher_rejects_total_drift() -> None:
    """Declared totals must remain stable throughout one traversal."""
    client = _QueueHttpClient(
        [
            page([product(1)], total=3),
            page([product(2)], total=2),
        ]
    )
    fetcher = GGSelFetcher(cast(HttpClient, client), max_pages=2)

    with pytest.raises(GGSelFetchError, match="total changed"):
        run_async(fetcher.fetch_complete_category(CATEGORY_URL))


def test_fetcher_rejects_early_empty_page() -> None:
    """An empty page before the declared total fails closed."""
    client = _QueueHttpClient(
        [
            page([product(1)], total=2),
            page([], total=2),
        ]
    )
    fetcher = GGSelFetcher(cast(HttpClient, client), max_pages=2)

    with pytest.raises(GGSelFetchError, match="ended before"):
        run_async(fetcher.fetch_complete_category(CATEGORY_URL))


def test_fetcher_enforces_page_bound() -> None:
    """A category that exceeds the configured bound is never marked complete."""
    client = _QueueHttpClient([page([product(1)], total=2)])
    fetcher = GGSelFetcher(cast(HttpClient, client), max_pages=1)

    with pytest.raises(GGSelFetchError, match="exceeded"):
        run_async(fetcher.fetch_complete_category(CATEGORY_URL))


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/en/catalog/minecraft-keys-pc",
        "http://ggsel.net/en/catalog/minecraft-keys-pc",
        "https://ggsel.net/en/product/minecraft-keys-pc",
    ],
)
def test_fetcher_rejects_unsupported_category_url(url: str) -> None:
    """Only canonical HTTPS GGSEL category paths configure API requests."""
    client = _QueueHttpClient([])
    fetcher = GGSelFetcher(cast(HttpClient, client))

    with pytest.raises(GGSelFetchError, match="source URL is unsupported"):
        run_async(fetcher.fetch_complete_category(url))

    assert client.gets == []


class _QueueHttpClient:
    """Capture GGSEL requests and return queued responses."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = iter(responses)
        self.gets: list[dict[str, Any]] = []

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        self.gets.append({"url": url, **kwargs})
        return next(self._responses)
