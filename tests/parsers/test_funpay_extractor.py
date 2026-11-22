from __future__ import annotations

from decimal import Decimal

from app.parsers.funpay_extractor import FunPayExtractor
from app.parsers.funpay_normalizer import FunPayNormalizer


def test_funpay_extractor_reads_offer_anchor() -> None:
    """FunPay extractor reads public offer anchors into ParsedOffer objects."""
    html = """
    <a href="https://funpay.com/en/lots/offer?id=67382658"
       class="tc-item"
       data-offer="67382658"
       data-online="1">
      <div class="tc-desc">
        <div class="tc-desc-text">Minecraft Premium Account</div>
      </div>
      <div class="tc-user">
        <div class="avatar-photo"
             data-href="https://funpay.com/users/42/"
             style="background-image: url(https://example.com/avatar.png);"></div>
        <div class="media-user-name">BestSeller</div>
        <div class="media-user-info">1 year</div>
        <div class="media-user-reviews">12 reviews</div>
      </div>
      <div class="tc-price" data-s="790"><div>790 \u20bd</div></div>
    </a>
    """

    offers = FunPayExtractor().extract(html)

    assert len(offers) == 1
    assert offers[0].marketplace == "funpay"
    assert offers[0].external_id == "67382658"
    assert offers[0].title == "Minecraft Premium Account"
    assert offers[0].url == "https://funpay.com/lots/offer?id=67382658"
    assert offers[0].price == Decimal("790")
    assert offers[0].currency == "RUB"
    assert offers[0].seller_id == "42"
    assert offers[0].seller_name == "BestSeller"
    assert offers[0].source_category_id is None
    assert offers[0].source_category_name is None


def test_funpay_extractor_deduplicates_offers_by_external_id() -> None:
    """Repeated FunPay offer links are emitted once."""
    html = """
    <a href="/lots/offer?id=1" class="tc-item" data-offer="1">
      <div class="tc-desc-text">Minecraft Premium</div>
      <div class="tc-price" data-s="1200"><div>1 200 \u20bd</div></div>
    </a>
    <a href="/lots/offer?id=1" class="tc-item" data-offer="1">
      <div class="tc-desc-text">Minecraft Premium</div>
      <div class="tc-price" data-s="1200"><div>1 200 \u20bd</div></div>
    </a>
    """

    offers = FunPayExtractor().extract(html)

    assert len(offers) == 1
    assert offers[0].price == Decimal("1200")
    assert offers[0].currency == "RUB"


def test_funpay_extractor_preserves_structured_source_parameters() -> None:
    """Terms stay source evidence and never become an inferred canonical link."""
    html = """
    <html><body><div class="showcase-table">
      <a href="/lots/offer?id=1" class="tc-item" data-offer="1"
         data-f-type="pc" data-f-time="1 месяц" data-f-method="цифровой код">
        <div class="tc-desc-text">Monthly code</div>
        <div class="tc-price" data-s="790"><div>790 ₽</div></div>
      </a>
    </div></body></html>
    """
    extractor = FunPayExtractor()
    with_parameters = extractor.extract_with_parameters(html)
    original_contract = extractor.extract_with_evidence(html)

    assert with_parameters.evidence == original_contract.evidence
    assert with_parameters.evidence.complete
    assert (
        tuple(item.offer for item in with_parameters.items) == original_contract.items
    )
    assert dict(with_parameters.items[0].parameters) == {
        "f-type": "pc",
        "f-time": "1 месяц",
        "f-method": "цифровой код",
        "offer": "1",
    }
    assert with_parameters.items[0].offer.canonical_product_id is None


def test_funpay_extractor_ignores_links_without_offer_id() -> None:
    """Navigation links are not treated as marketplace offers."""
    html = '<a href="/lots/221/">Minecraft</a>'

    assert FunPayExtractor().extract(html) == []


def test_funpay_normalizer_preserves_snapshot_ready_fields() -> None:
    """FunPay normalizer keeps universal fields required by SnapshotBuilder."""
    html = """
    <a href="/lots/offer?id=2" class="tc-item" data-offer="2">
      <div class="tc-desc-text"> Minecraft   Premium </div>
      <div class="tc-price" data-s="790"><div>790 \u20bd</div></div>
    </a>
    """

    normalized = FunPayNormalizer().normalize(FunPayExtractor().extract(html))

    assert len(normalized) == 1
    assert normalized[0].marketplace == "funpay"
    assert normalized[0].title == "Minecraft Premium"
    assert normalized[0].price == Decimal("790")
    assert normalized[0].currency == "RUB"
    assert normalized[0].seller_name is None


def test_funpay_extractor_preserves_decimal_euro_price() -> None:
    """FunPay prices retain decimal precision and their source currency."""
    html = """
    <a href="/en/lots/offer?id=3" class="tc-item" data-offer="3">
      <div class="tc-desc-text">Minecraft Gift</div>
      <div class="tc-price" data-s="22.60"><div>22.60 \u20ac</div></div>
    </a>
    """

    offers = FunPayExtractor().extract(html)

    assert len(offers) == 1
    assert offers[0].price == Decimal("22.6")
    assert offers[0].currency == "EUR"


def test_funpay_extractor_uses_buyer_visible_price_precision() -> None:
    """Hidden conversion precision does not create sub-cent price changes."""
    html = """
    <a href="/lots/offer?id=4" class="tc-item" data-offer="4">
      <div class="tc-desc-text">Minecraft Account</div>
      <div class="tc-price" data-s="329.9389"><div>329.94 \u20bd</div></div>
    </a>
    """

    offers = FunPayExtractor().extract(html)

    assert offers[0].price == Decimal("329.94")


def test_funpay_extractor_proves_closed_unpaginated_showcase_complete() -> None:
    """A structurally closed showcase with full ID coverage is reconcilable."""
    html = """
    <html><body>
      <div class="tc showcase-table">
        <a href="/lots/offer?id=1" class="tc-item" data-offer="1">
          <div class="tc-desc-text">Minecraft Premium</div>
          <div class="tc-price" data-s="790"><div>790 ₽</div></div>
        </a>
      </div>
    </body></html>
    """

    extraction = FunPayExtractor().extract_with_evidence(html)

    assert len(extraction.items) == 1
    assert extraction.evidence.source_items == 1
    assert extraction.evidence.parsed_items == 1
    assert extraction.evidence.complete is True


def test_funpay_extractor_rejects_paginated_showcase() -> None:
    """Visible pagination prevents a listing from driving deactivation."""
    html = """
    <html><body>
      <div class="tc showcase-table">
        <a href="/lots/offer?id=1" class="tc-item" data-offer="1">
          <div class="tc-desc-text">Minecraft Premium</div>
          <div class="tc-price" data-s="790"><div>790 ₽</div></div>
        </a>
      </div>
      <nav class="pagination"><a rel="next" href="?page=2">Next</a></nav>
    </body></html>
    """

    extraction = FunPayExtractor().extract_with_evidence(html)

    assert extraction.evidence.complete is False
    assert extraction.evidence.reason == (
        "FunPay response exposes a pagination control."
    )


def test_funpay_extractor_rejects_unclosed_listing_document() -> None:
    """A truncated response remains safe from missing-offer reconciliation."""
    html = """
    <html><body><div class="tc showcase-table">
      <a href="/lots/offer?id=1" class="tc-item" data-offer="1">
        <div class="tc-desc-text">Minecraft Premium</div>
        <div class="tc-price" data-s="790"><div>790 ₽</div></div>
      </a>
    </div>
    """

    extraction = FunPayExtractor().extract_with_evidence(html)

    assert extraction.evidence.complete is False
    assert extraction.evidence.reason == (
        "FunPay response is not a closed HTML document."
    )
