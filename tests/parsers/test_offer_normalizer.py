from __future__ import annotations

from decimal import Decimal

from app.parsers.models import RawMarketplaceOffer
from app.parsers.normalizers import OfferNormalizer


def test_ggsel_normalizer_builds_absolute_urls_from_slugs() -> None:
    """GGSEL slugs become stable absolute product URLs."""
    parsed = OfferNormalizer(marketplace="ggsel").normalize(
        _raw_offer(url="minecraft-premium-123"),
    )

    assert parsed.url == "https://ggsel.net/catalog/minecraft-premium-123"


def test_ggsel_normalizer_preserves_absolute_urls() -> None:
    """Existing absolute URLs are not rewritten."""
    parsed = OfferNormalizer(marketplace="ggsel").normalize(
        _raw_offer(url="https://ggsel.net/catalog/minecraft-premium-123"),
    )

    assert parsed.url == "https://ggsel.net/catalog/minecraft-premium-123"


def test_normalizer_keeps_relative_urls_without_base_url() -> None:
    """Non-GGSEL usage remains opt-in for URL expansion."""
    parsed = OfferNormalizer(marketplace="custom").normalize(
        _raw_offer(url="minecraft-premium-123"),
    )

    assert parsed.url == "minecraft-premium-123"


def test_normalizer_keeps_snapshot_required_fields() -> None:
    """Normalization preserves fields needed by SnapshotBuilder."""
    parsed = OfferNormalizer(marketplace="ggsel").normalize(
        _raw_offer(url="minecraft-premium-123"),
    )

    assert parsed.marketplace == "ggsel"
    assert parsed.external_id == "123"
    assert parsed.title == "Minecraft Premium"
    assert parsed.price == Decimal("790.0")
    assert parsed.currency == "RUB"
    assert parsed.seller_id == "456"
    assert parsed.seller_name == "Seller"


def _raw_offer(url: str) -> RawMarketplaceOffer:
    return RawMarketplaceOffer(
        id_goods=123,
        name=" Minecraft   Premium ",
        url=url,
        seller_name=" Seller ",
        id_section=789,
        image=None,
        price=790.0,
        currency="rub",
        extra={"id_seller": 456},
    )
