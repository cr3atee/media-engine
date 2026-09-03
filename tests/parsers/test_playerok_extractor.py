from __future__ import annotations

from decimal import Decimal

from app.parsers.playerok_extractor import PlayerokExtractor
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
