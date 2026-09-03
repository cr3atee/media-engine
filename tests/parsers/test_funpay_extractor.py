from __future__ import annotations

from decimal import Decimal

from app.parsers.funpay_extractor import FunPayExtractor
from app.parsers.funpay_normalizer import FunPayNormalizer


def test_funpay_extractor_reads_offer_anchor() -> None:
    """FunPay extractor reads public offer anchors into ParsedOffer objects."""
    html = """
    <a href="https://funpay.com/en/lots/offer?id=67382658" class="tc-item">
      <div class="tc-desc">
        <div class="tc-desc-text">Minecraft Premium Account</div>
      </div>
      <div class="media-user-name">BestSeller</div>
      <div class="tc-price">790 ₽</div>
    </a>
    """

    offers = FunPayExtractor().extract(html)

    assert len(offers) == 1
    assert offers[0].marketplace == "funpay"
    assert offers[0].external_id == "67382658"
    assert offers[0].title == "Minecraft Premium Account"
    assert offers[0].url == "https://funpay.com/en/lots/offer?id=67382658"
    assert offers[0].price == Decimal("790")
    assert offers[0].currency == "RUB"
    assert offers[0].seller_name == "BestSeller"


def test_funpay_extractor_deduplicates_offers_by_external_id() -> None:
    """Repeated FunPay offer links are emitted once."""
    html = """
    <a href="/lots/offer?id=1" class="tc-item">
      <div class="tc-desc-text">Minecraft Premium</div>
      <div class="tc-price">1 200 RUB</div>
    </a>
    <a href="/lots/offer?id=1" class="tc-item">
      <div class="tc-desc-text">Minecraft Premium</div>
      <div class="tc-price">1 200 RUB</div>
    </a>
    """

    offers = FunPayExtractor().extract(html)

    assert len(offers) == 1
    assert offers[0].price == Decimal("1200")
    assert offers[0].currency == "RUB"


def test_funpay_extractor_ignores_links_without_offer_id() -> None:
    """Navigation links are not treated as marketplace offers."""
    html = '<a href="/lots/221/">Minecraft</a>'

    assert FunPayExtractor().extract(html) == []


def test_funpay_normalizer_preserves_snapshot_ready_fields() -> None:
    """FunPay normalizer keeps universal fields required by SnapshotBuilder."""
    html = """
    <a href="/lots/offer?id=2" class="tc-item">
      <div class="tc-desc-text"> Minecraft   Premium </div>
      <div class="media-user-name"> Seller </div>
      <div class="tc-price">790 rub</div>
    </a>
    """

    normalized = FunPayNormalizer().normalize(FunPayExtractor().extract(html))

    assert len(normalized) == 1
    assert normalized[0].marketplace == "funpay"
    assert normalized[0].title == "Minecraft Premium"
    assert normalized[0].price == Decimal("790")
    assert normalized[0].currency == "RUB"
    assert normalized[0].seller_name == "Seller"
