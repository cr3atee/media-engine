from __future__ import annotations

from decimal import Decimal

from app.parsers.models import ParsedOffer
from scripts.run_catalog_review_preview import _select_aligned_review_offers
from scripts.verify_aligned_marketplace_categories import MarketplaceCategoryBatch


def test_aligned_review_batch_selects_one_pair_per_source_combination() -> None:
    """The bounded batch reuses top evidence and deduplicates shared offers."""
    shared_ggsel = _offer("ggsel", "ggsel-base", "Minecraft Java Bedrock")
    other_ggsel = _offer("ggsel", "ggsel-other", "Telegram Stars")
    playerok = _offer("playerok", "playerok-base", "Minecraft Java Bedrock")
    funpay = _offer("funpay", "funpay-base", "Minecraft Java Bedrock")
    batches = (
        _batch("ggsel", shared_ggsel, other_ggsel),
        _batch("playerok", playerok),
        _batch("funpay", funpay),
    )

    selected = _select_aligned_review_offers(batches)

    assert [(offer.marketplace, offer.external_id) for offer in selected] == [
        ("funpay", "funpay-base"),
        ("ggsel", "ggsel-base"),
        ("playerok", "playerok-base"),
    ]


def test_aligned_review_batch_returns_empty_without_cross_source_pair() -> None:
    """One marketplace cannot produce cross-source review evidence."""
    selected = _select_aligned_review_offers(
        (_batch("ggsel", _offer("ggsel", "one", "Minecraft")),)
    )

    assert selected == ()


def _batch(
    marketplace: str,
    *offers: ParsedOffer,
) -> MarketplaceCategoryBatch:
    return MarketplaceCategoryBatch(
        marketplace=marketplace,
        source_total=len(offers),
        offers=offers,
        snapshot_ready_offers=offers,
    )


def _offer(
    marketplace: str,
    external_id: str,
    title: str,
) -> ParsedOffer:
    return ParsedOffer(
        marketplace=marketplace,
        external_id=external_id,
        title=title,
        url=f"https://example.com/{external_id}",
        price=Decimal("1000"),
        currency="RUB",
    )
