from __future__ import annotations

from app.parsers.ggsel_extractor import GGSelExtractor
from app.parsers.source_snapshot import SourceExtraction, SourceSnapshotEvidence


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


def test_ggsel_extractor_marks_partial_declared_listing_incomplete() -> None:
    """A first page smaller than GGSEL's declared total is not reconcilable."""
    html = """
    <html><body><script>
      self.__next_f.push([{
        "items": [{
          "id_goods": 1,
          "name": "Minecraft Premium",
          "url": "minecraft-premium-1",
          "seller_name": "Seller",
          "id_section": 2,
          "price_wmr": "790"
        }],
        "total": 2
      }])
    </script></body></html>
    """

    extraction = GGSelExtractor().extract_with_evidence(html)

    assert len(extraction.items) == 1
    assert extraction.evidence.source_items == 1
    assert extraction.evidence.parsed_items == 1
    assert extraction.evidence.expected_items == 2
    assert extraction.evidence.complete is False
    assert extraction.evidence.reason == "GGSEL embedded 1 of 2 declared products."


def test_ggsel_extractor_marks_fully_covered_listing_complete() -> None:
    """Matching identities and source total prove a bounded GGSEL snapshot."""
    html = """
    <html><body><script>
      self.__next_f.push([{
        "items": [{
          "id_goods": 1,
          "name": "Minecraft Premium",
          "url": "minecraft-premium-1",
          "seller_name": "Seller",
          "id_section": 2,
          "price_wmr": "790"
        }],
        "total": 1
      }])
    </script></body></html>
    """

    extraction = GGSelExtractor().extract_with_evidence(html)

    assert extraction.evidence.complete is True
    assert extraction.evidence.expected_items == 1


def test_ggsel_extractor_rejects_show_more_even_when_total_matches() -> None:
    """An explicit pagination control always keeps reconciliation disabled."""
    html = """
    <html><body><script>
      self.__next_f.push([{
        "items": [{
          "id_goods": 1,
          "name": "Minecraft Premium",
          "url": "minecraft-premium-1",
          "seller_name": "Seller",
          "id_section": 2,
          "price_wmr": "790"
        }],
        "total": 1
      }])
    </script><button data-test="showMore">More</button></body></html>
    """

    extraction = GGSelExtractor().extract_with_evidence(html)

    assert extraction.evidence.complete is False
    assert extraction.evidence.reason == (
        "GGSEL response exposes a show-more pagination control."
    )


def test_ggsel_extractor_preserves_paginated_source_evidence() -> None:
    """Typed products remain complete when every API identity is extracted."""
    raw_items = (
        {
            "id_goods": 1,
            "name": "Minecraft Premium",
            "url": "minecraft-premium-1",
            "seller_name": "Seller",
            "id_section": 2,
            "price_wmr": "790",
        },
    )
    source = SourceExtraction(
        items=raw_items,
        evidence=SourceSnapshotEvidence(
            source_items=1,
            parsed_items=1,
            expected_items=1,
            complete=True,
            reason="Transport covered the declared total.",
        ),
    )

    extraction = GGSelExtractor().extract_source_items(source)

    assert len(extraction.items) == 1
    assert extraction.items[0].id_goods == 1
    assert extraction.evidence.complete is True


def test_ggsel_extractor_marks_unmapped_api_item_incomplete() -> None:
    """Transport coverage cannot hide a product that mapping rejected."""
    raw_items = (
        {
            "id_goods": 1,
            "name": "Minecraft Premium",
            "url": "minecraft-premium-1",
            "seller_name": "Seller",
            "id_section": 2,
            "price_wmr": "790",
        },
        {"id_goods": 2, "name": "Incomplete"},
    )
    source = SourceExtraction(
        items=raw_items,
        evidence=SourceSnapshotEvidence(
            source_items=2,
            parsed_items=2,
            expected_items=2,
            complete=True,
            reason="Transport covered the declared total.",
        ),
    )

    extraction = GGSelExtractor().extract_source_items(source)

    assert len(extraction.items) == 1
    assert extraction.evidence.complete is False
    assert extraction.evidence.source_items == 2
