from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import cast

import httpx

from app.core.http_client import HttpClient
from app.parsers.playerok_extractor import PlayerokExtractor
from app.parsers.playerok_fetcher import PlayerokFetcher, PlayerokFetchError
from app.parsers.playerok_normalizer import PlayerokNormalizer


def test_playerok_extractor_reads_json_offer_payload() -> None:
    """Playerok extractor maps a structured JSON offer into ParsedOffer."""
    raw_response = """
    {
      "products": [
        {
          "id": "offer-1",
          "slug": "minecraft-premium",
          "name": " Minecraft Premium ",
          "price": {"amount": "790.50", "currency": "rub"},
          "seller": {"id": 123, "username": "BestSeller"}
        }
      ]
    }
    """

    offers = PlayerokExtractor().extract(raw_response)

    assert len(offers) == 1
    assert offers[0].marketplace == "playerok"
    assert offers[0].external_id == "offer-1"
    assert offers[0].title == "Minecraft Premium"
    assert offers[0].url == "https://playerok.com/products/minecraft-premium"
    assert offers[0].price == Decimal("790.50")
    assert offers[0].currency == "RUB"
    assert offers[0].seller_id == "123"
    assert offers[0].seller_name == "BestSeller"


def test_playerok_extractor_reads_next_data_payload() -> None:
    """Playerok extractor can inspect saved Next.js hydration responses."""
    raw_response = """
    <html>
      <script id="__NEXT_DATA__" type="application/json">
        {
          "props": {
            "pageProps": {
              "items": [
                {
                  "id": 2,
                  "slug": "playerok-minecraft",
                  "title": "Playerok Minecraft",
                  "price": 790,
                  "currency": "RUB",
                  "user": {"id": "seller-1", "name": "Seller"}
                }
              ]
            }
          }
        }
      </script>
    </html>
    """

    offers = PlayerokExtractor().extract(raw_response)

    assert len(offers) == 1
    assert offers[0].external_id == "2"
    assert offers[0].title == "Playerok Minecraft"
    assert offers[0].price == Decimal("790")
    assert offers[0].currency == "RUB"
    assert offers[0].seller_id == "seller-1"
    assert offers[0].seller_name == "Seller"


def test_playerok_extractor_ignores_payload_without_identifier() -> None:
    """Objects without stable id or slug are not treated as offers."""
    raw_response = '{"products": [{"name": "Minecraft Premium", "price": 790}]}'

    assert PlayerokExtractor().extract(raw_response) == []


def test_playerok_extractor_ignores_catalog_nodes_without_price() -> None:
    """Catalog and game nodes are not marketplace offers."""
    raw_response = """
    {
      "data": {
        "items": {
          "edges": [
            {
              "node": {
                "id": "offer-1",
                "slug": "minecraft-premium",
                "name": "Minecraft Premium",
                "price": 790,
                "category": {
                  "id": "category-1",
                  "slug": "keys",
                  "name": "Keys"
                },
                "game": {
                  "id": "game-1",
                  "slug": "minecraft",
                  "name": "Minecraft"
                }
              }
            }
          ]
        }
      }
    }
    """

    offers = PlayerokExtractor().extract(raw_response)

    assert len(offers) == 1
    assert offers[0].external_id == "offer-1"


def test_playerok_normalizer_preserves_snapshot_ready_fields() -> None:
    """Playerok normalizer keeps universal fields required by SnapshotBuilder."""
    raw_response = """
    {
      "items": [
        {
          "id": "offer-2",
          "slug": "minecraft-premium",
          "name": " Minecraft   Premium ",
          "price": "790",
          "currency": "rub",
          "owner": {"id": 456, "username": " Seller "}
        }
      ]
    }
    """

    normalized = PlayerokNormalizer().normalize(
        PlayerokExtractor().extract(raw_response)
    )

    assert len(normalized) == 1
    assert normalized[0].marketplace == "playerok"
    assert normalized[0].external_id == "offer-2"
    assert normalized[0].title == "Minecraft Premium"
    assert normalized[0].price == Decimal("790")
    assert normalized[0].currency == "RUB"
    assert normalized[0].seller_id == "456"
    assert normalized[0].seller_name == "Seller"


def test_playerok_normalizer_defaults_missing_currency_to_rub() -> None:
    """Playerok item-list prices are normalized to the source-backed RUB default."""
    raw_response = """
    {
      "items": [
        {
          "id": "offer-3",
          "slug": "minecraft-premium",
          "name": "Minecraft Premium",
          "price": 790,
          "user": {"id": "seller-1", "username": "Seller"}
        }
      ]
    }
    """

    normalized = PlayerokNormalizer().normalize(
        PlayerokExtractor().extract(raw_response)
    )

    assert len(normalized) == 1
    assert normalized[0].currency == "RUB"


def test_playerok_fetcher_uses_graphql_items_by_default() -> None:
    """Playerok fetcher uses the discovered GraphQL items operation by default."""
    fake_client = _FakeHttpClient(
        httpx.Response(200, json={"data": {"items": {"edges": []}}}),
    )
    fetcher = PlayerokFetcher(cast(HttpClient, fake_client))

    response = asyncio.run(fetcher.fetch())

    assert response == '{"data":{"items":{"edges":[]}}}'
    assert fake_client.posts[0]["url"] == PlayerokFetcher.GRAPHQL_URL
    payload = fake_client.posts[0]["json"]
    assert isinstance(payload, dict)
    assert payload["operationName"] == "items"
    assert "query items" in str(payload["query"])
    assert payload["variables"] == {
        "filter": {"status": ["APPROVED"]},
        "pagination": {"first": 20, "after": None},
        "showForbiddenImage": True,
    }


def test_playerok_fetcher_rejects_empty_response() -> None:
    """Playerok fetcher does not treat empty marketplace responses as data."""
    fetcher = PlayerokFetcher(
        cast(HttpClient, _FakeHttpClient(httpx.Response(200, text="  "))),
    )

    try:
        asyncio.run(fetcher.fetch())
    except PlayerokFetchError as exc:
        assert "empty response" in str(exc)
        assert fetcher.last_diagnostic == "Playerok returned an empty response body"
    else:
        raise AssertionError("Expected PlayerokFetchError")


class _FakeHttpClient:
    """Small test double for the shared project HTTP client."""

    def __init__(self, response: httpx.Response) -> None:
        self._response = response
        self.posts: list[dict[str, object]] = []

    async def post(self, url: str, **kwargs: object) -> httpx.Response:
        self.posts.append({"url": url, **kwargs})
        return self._response
