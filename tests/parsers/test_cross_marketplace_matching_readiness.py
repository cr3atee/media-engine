from __future__ import annotations

from decimal import Decimal

import pytest

from app.matching.confidence import MatchDecision
from app.parsers.models import ParsedOffer
from scripts.analyze_cross_marketplace_matching import (
    analyze_cross_marketplace_matching,
)
from scripts.verify_marketplace_data_readiness import MarketplaceReadiness
from scripts.verify_public_ui_readiness import build_seeded_products


def test_analysis_finds_deterministic_automatic_match() -> None:
    """Equivalent normalized titles provide automatic grouping evidence."""
    report = analyze_cross_marketplace_matching(
        {
            "playerok": (_offer("playerok", "2", "Minecraft / Premium"),),
            "ggsel": (_offer("ggsel", "1", "minecraft-premium"),),
        }
    )

    assert report.marketplace_count == 2
    assert report.offer_count == 2
    assert report.comparable_offer_count == 2
    assert report.pair_count == 1
    assert report.auto_match_count == 1
    assert report.review_count == 0
    assert report.no_match_count == 0
    assert report.highest_similarity == 1.0
    assert report.automatic_grouping_ready is True
    assert report.top_candidates[0].decision is MatchDecision.AUTO_MATCH
    assert report.top_candidates[0].left_marketplace == "ggsel"


def test_analysis_keeps_unrelated_offers_unmatched() -> None:
    """Unrelated marketplace titles do not become fabricated comparisons."""
    report = analyze_cross_marketplace_matching(
        {
            "ggsel": (_offer("ggsel", "1", "Minecraft Premium"),),
            "playerok": (_offer("playerok", "2", "Telegram Stars"),),
        }
    )

    assert report.pair_count == 1
    assert report.auto_match_count == 0
    assert report.review_count == 0
    assert report.no_match_count == 1
    assert report.automatic_grouping_ready is False


def test_analysis_skips_missing_titles_and_validates_limit() -> None:
    """Missing titles cannot accidentally compare as identical empty token sets."""
    report = analyze_cross_marketplace_matching(
        {
            "ggsel": (_offer("ggsel", "1", None),),
            "playerok": (_offer("playerok", "2", "  "),),
        }
    )

    assert report.offer_count == 2
    assert report.comparable_offer_count == 0
    assert report.pair_count == 0
    assert report.highest_similarity == 0.0

    with pytest.raises(ValueError, match="top_limit must not be negative"):
        analyze_cross_marketplace_matching({}, top_limit=-1)


def test_public_preview_discloses_separate_canonical_products() -> None:
    """Saved-payload preview does not imply unverified marketplace matching."""
    readiness = (
        _readiness("ggsel", _offer("ggsel", "1", "Minecraft Premium")),
        _readiness("playerok", _offer("playerok", "2", "Telegram Stars")),
    )

    products, notes = build_seeded_products(readiness)

    assert len(products) == 2
    assert any("does not claim cross-marketplace identity" in note for note in notes)
    assert products[0].product.id != products[1].product.id


def _offer(
    marketplace: str,
    external_id: str,
    title: str | None,
) -> ParsedOffer:
    return ParsedOffer(
        marketplace=marketplace,
        external_id=external_id,
        title=title,
        url=f"https://example.com/{external_id}",
        price=Decimal("790"),
        currency="RUB",
    )


def _readiness(
    marketplace: str,
    offer: ParsedOffer,
) -> MarketplaceReadiness:
    return MarketplaceReadiness(
        marketplace=marketplace,
        status="ready",
        raw_items=1,
        parsed_offers=1,
        snapshot_ready_offers=1,
        notes=(),
        examples=(offer,),
    )
