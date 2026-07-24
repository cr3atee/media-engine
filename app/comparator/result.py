from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from app.comparator.difference import ComparisonDifferenceResult, OfferDifference
from app.comparator.models import MarketplaceOffer, ProductComparisonInput
from app.comparator.selector import BestOfferSelection
from app.models.canonical_product import CanonicalProduct


class ComparisonStatus(str, Enum):
    """Deterministic comparison status values."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    CURRENCY_MISMATCH = "currency_mismatch"
    NO_VALID_PRICES = "no_valid_prices"
    UNMATCHED = "unmatched"


@dataclass(slots=True, frozen=True)
class ComparisonResult:
    """Immutable comparison result for one canonical product."""

    canonical_product_id: UUID | None
    canonical_product: CanonicalProduct | None
    grouped_offers: tuple[MarketplaceOffer, ...]
    best_offer: MarketplaceOffer | None
    comparison_entries: tuple[OfferDifference, ...]
    status: ComparisonStatus


class ComparisonResultBuilder:
    """Builds a single comparison result from existing comparator DTOs."""

    def build(
        self,
        canonical_product: CanonicalProduct | None,
        selection: BestOfferSelection,
        difference: ComparisonDifferenceResult,
    ) -> ComparisonResult:
        """Return an immutable comparison result for one canonical product."""
        grouped_offers = selection.comparison.offers
        return ComparisonResult(
            canonical_product_id=canonical_product.id if canonical_product else None,
            canonical_product=canonical_product,
            grouped_offers=grouped_offers,
            best_offer=difference.best_offer,
            comparison_entries=difference.differences,
            status=self._status(canonical_product, selection, difference),
        )

    def _status(
        self,
        canonical_product: CanonicalProduct | None,
        selection: BestOfferSelection,
        difference: ComparisonDifferenceResult,
    ) -> ComparisonStatus:
        if (
            canonical_product is None
            and selection.comparison.canonical_product_id is None
        ):
            return ComparisonStatus.UNMATCHED
        if (
            selection.reason == "currency mismatch"
            or difference.reason == "currency mismatch"
        ):
            return ComparisonStatus.CURRENCY_MISMATCH
        if selection.selected_offer is None:
            return ComparisonStatus.NO_VALID_PRICES
        if any(entry.reason is not None for entry in difference.differences):
            return ComparisonStatus.PARTIAL
        return ComparisonStatus.COMPLETE
