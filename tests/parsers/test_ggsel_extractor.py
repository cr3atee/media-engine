from __future__ import annotations

from app.parsers.ggsel_extractor import GGSelExtractor


def test_ggsel_extractor_reads_embedded_product_payload() -> None:
    """GGSEL extractor returns typed raw offers from embedded payload data."""
    html = """
    <html>
      <body>
        <script>
          self.__next_f.push([{
            "id_goods": 4040511,
            "name": " Minecraft Premium ",
            "url": "minecraft-premium-4040511",
            "seller_name": "Seller",
            "id_section": 28831,
            "image": "https://img.ggsel.net/example.webp",
            "price_wmr": "790.50",
            "id_seller": 123
          }])
        </script>
      </body>
    </html>
    """

    offers = GGSelExtractor().extract(html)

    assert len(offers) == 1
    assert offers[0].id_goods == 4040511
    assert offers[0].name == "Minecraft Premium"
    assert offers[0].url == "minecraft-premium-4040511"
    assert offers[0].seller_name == "Seller"
    assert offers[0].id_section == 28831
    assert offers[0].image == "https://img.ggsel.net/example.webp"
    assert offers[0].price == 790.50
    assert offers[0].currency == "RUB"
    assert offers[0].extra["id_seller"] == 123


def test_ggsel_extractor_deduplicates_products_by_id() -> None:
    """Repeated GGSEL product objects are emitted once."""
    product = """
    {
      "id_goods": 1,
      "name": "Minecraft Premium",
      "url": "minecraft-premium-1",
      "seller_name": "Seller",
      "id_section": 2,
      "price_wmz": "10"
    }
    """
    html = f"<script>self.__next_f.push([{product}, {product}])</script>"

    offers = GGSelExtractor().extract(html)

    assert len(offers) == 1
    assert offers[0].price == 10.0
    assert offers[0].currency == "USD"


def test_ggsel_extractor_ignores_incomplete_payloads() -> None:
    """Incomplete embedded objects do not become raw marketplace offers."""
    html = """
    <script>
      self.__next_f.push([{
        "id_goods": 4040511,
        "name": "Minecraft Premium",
        "url": "minecraft-premium-4040511"
      }])
    </script>
    """

    assert GGSelExtractor().extract(html) == []
