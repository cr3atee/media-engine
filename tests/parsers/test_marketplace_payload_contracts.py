from __future__ import annotations

from app.parsers.models import ParsedOffer
from scripts.verify_marketplace_data_readiness import MarketplaceReadiness
from scripts.verify_marketplace_payload_contracts import (
    MarketplacePayloadExpectation,
    validate_readiness,
    validate_source_categories,
)


def test_validate_readiness_accepts_ready_marketplace() -> None:
    """Ready marketplace payloads satisfy the minimum contract."""
    result = MarketplaceReadiness(
        marketplace="ggsel",
        status="ready",
        raw_items=1,
        parsed_offers=1,
        snapshot_ready_offers=1,
        notes=(),
    )

    assert (
        validate_readiness(
            (result,),
            (MarketplacePayloadExpectation(marketplace="ggsel"),),
        )
        == ()
    )


def test_validate_readiness_reports_missing_marketplace() -> None:
    """The drift guard fails when an expected marketplace is absent."""
    violations = validate_readiness(
        (),
        (MarketplacePayloadExpectation(marketplace="ggsel"),),
    )

    assert violations == ("ggsel: missing readiness result",)


def test_validate_readiness_reports_status_and_count_violations() -> None:
    """Partial payloads show every failed readiness dimension."""
    result = MarketplaceReadiness(
        marketplace="playerok",
        status="partial",
        raw_items=1,
        parsed_offers=0,
        snapshot_ready_offers=0,
        notes=(),
    )

    violations = validate_readiness(
        (result,),
        (MarketplacePayloadExpectation(marketplace="playerok"),),
    )

    assert violations == (
        "playerok: status 'partial', expected 'ready'",
        "playerok: parsed offers 0, expected at least 1",
        "playerok: snapshot-ready offers 0, expected at least 1",
    )


def test_validate_source_categories_accepts_exact_adapter_evidence() -> None:
    offers = {
        "ggsel": (_offer("ggsel", source_id="28831"),),
        "playerok": (_offer("playerok", source_id="keys", source_name="Digital keys"),),
        "funpay": (_offer("funpay"),),
    }

    assert validate_source_categories(offers) == ()


def test_validate_source_categories_reports_required_coverage() -> None:
    violations = validate_source_categories(
        {
            "ggsel": (_offer("ggsel"),),
            "playerok": (_offer("playerok", source_id="keys"),),
        }
    )

    assert violations == (
        "ggsel: source category ID coverage is incomplete",
        "playerok: source category name coverage is incomplete",
    )


def _offer(
    marketplace: str,
    *,
    source_id: str | None = None,
    source_name: str | None = None,
) -> ParsedOffer:
    return ParsedOffer(
        marketplace=marketplace,
        external_id="offer-1",
        title="Offer",
        url="https://example.com/offer-1",
        price=None,
        currency=None,
        source_category_id=source_id,
        source_category_name=source_name,
    )
