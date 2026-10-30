from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.parsers.models import ParsedOffer  # noqa: E402
from scripts.verify_marketplace_data_readiness import (  # noqa: E402
    MarketplaceReadiness,
    load_saved_marketplace_offers,
    verify_funpay,
    verify_ggsel,
    verify_playerok,
)


@dataclass(slots=True, frozen=True)
class MarketplacePayloadExpectation:
    """Minimum saved-payload contract required for one marketplace."""

    marketplace: str
    min_raw_items: int = 1
    min_parsed_offers: int = 1
    min_snapshot_ready_offers: int = 1
    required_status: str = "ready"


DEFAULT_EXPECTATIONS = (
    MarketplacePayloadExpectation(marketplace="ggsel"),
    MarketplacePayloadExpectation(marketplace="playerok"),
    MarketplacePayloadExpectation(marketplace="funpay"),
)

SOURCE_CATEGORY_REQUIREMENTS = {
    "ggsel": (True, False),
    "playerok": (True, True),
}


def collect_readiness() -> tuple[MarketplaceReadiness, ...]:
    """Collect offline readiness results from saved marketplace payloads."""
    return (
        verify_ggsel(),
        verify_playerok(),
        verify_funpay(),
    )


def validate_readiness(
    results: Sequence[MarketplaceReadiness],
    expectations: Sequence[MarketplacePayloadExpectation] = DEFAULT_EXPECTATIONS,
) -> tuple[str, ...]:
    """Return deterministic payload contract violations."""
    by_marketplace = {result.marketplace: result for result in results}
    violations: list[str] = []

    for expectation in expectations:
        result = by_marketplace.get(expectation.marketplace)
        if result is None:
            violations.append(f"{expectation.marketplace}: missing readiness result")
            continue

        if result.status != expectation.required_status:
            violations.append(
                f"{expectation.marketplace}: status {result.status!r}, "
                f"expected {expectation.required_status!r}"
            )

        if result.raw_items < expectation.min_raw_items:
            violations.append(
                f"{expectation.marketplace}: raw items {result.raw_items}, "
                f"expected at least {expectation.min_raw_items}"
            )

        if result.parsed_offers < expectation.min_parsed_offers:
            violations.append(
                f"{expectation.marketplace}: parsed offers {result.parsed_offers}, "
                f"expected at least {expectation.min_parsed_offers}"
            )

        if result.snapshot_ready_offers < expectation.min_snapshot_ready_offers:
            violations.append(
                f"{expectation.marketplace}: snapshot-ready offers "
                f"{result.snapshot_ready_offers}, expected at least "
                f"{expectation.min_snapshot_ready_offers}"
            )

    return tuple(violations)


def validate_source_categories(
    offers_by_marketplace: Mapping[str, Sequence[ParsedOffer]],
) -> tuple[str, ...]:
    """Return violations for source category evidence promised by adapters."""
    violations: list[str] = []
    for marketplace, (require_id, require_name) in SOURCE_CATEGORY_REQUIREMENTS.items():
        offers = offers_by_marketplace.get(marketplace, ())
        if not offers:
            violations.append(f"{marketplace}: no offers for source category check")
            continue
        if require_id and any(offer.source_category_id is None for offer in offers):
            violations.append(
                f"{marketplace}: source category ID coverage is incomplete"
            )
        if require_name and any(offer.source_category_name is None for offer in offers):
            violations.append(
                f"{marketplace}: source category name coverage is incomplete"
            )
    return tuple(violations)


def main() -> int:
    """Run the strict marketplace payload drift guard."""
    _configure_stdout()
    results = collect_readiness()
    offers_by_marketplace = load_saved_marketplace_offers()
    violations = (
        *validate_readiness(results),
        *validate_source_categories(offers_by_marketplace),
    )

    print("=== MARKETPLACE PAYLOAD CONTRACTS ===")
    for result in results:
        print(
            f"{result.marketplace}: "
            f"status={result.status}, "
            f"raw={result.raw_items}, "
            f"parsed={result.parsed_offers}, "
            f"snapshot_ready={result.snapshot_ready_offers}"
        )
    print()
    for marketplace, offers in offers_by_marketplace.items():
        category_ids = sum(offer.source_category_id is not None for offer in offers)
        category_names = sum(offer.source_category_name is not None for offer in offers)
        print(
            f"{marketplace}: source_category_id={category_ids}/{len(offers)}, "
            f"source_category_name={category_names}/{len(offers)}"
        )

    if violations:
        print()
        print("Payload contract violations:")
        for violation in violations:
            print(f"- {violation}")
        return 1

    print()
    print("All marketplace payload contracts are ready.")
    return 0


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")


if __name__ == "__main__":
    raise SystemExit(main())
