from __future__ import annotations

from scripts.verify_marketplace_data_readiness import MarketplaceReadiness
from scripts.verify_marketplace_payload_contracts import (
    MarketplacePayloadExpectation,
    validate_readiness,
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
