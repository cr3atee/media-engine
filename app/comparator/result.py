from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from app.comparator.difference import ComparisonDifferenceResult, OfferDifference
from app.comparator.models import MarketplaceOffer
from app.comparator.models import ProductComparisonInput as ProductComparisonInput
from app.comparator.selector import BestOfferSelection
from app.models.canonical_product import CanonicalProduct


class ComparisonStatus(str, Enum):  # noqa: UP042
    """Deterministic values; retain the existing public Enum string behavior."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    CURRENCY_MISMATCH = "currency_mismatch"
    NO_VALID_PRICES = "no_valid_prices"
    UNMATCHED = "unmatched"
    ACTIVATION_UNKNOWN = "activation_conditions_unknown"
    ACTIVATION_MISMATCH = "activation_conditions_mismatch"
    PRICE_ONLY = "price_only"


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
        if difference.reason == "activation conditions unknown":
            return ComparisonStatus.ACTIVATION_UNKNOWN
        if difference.reason == "activation conditions mismatch":
            return ComparisonStatus.ACTIVATION_MISMATCH
        if (
            selection.reason == "currency mismatch"
            or difference.reason == "currency mismatch"
        ):
            return ComparisonStatus.CURRENCY_MISMATCH
        if selection.selected_offer is None:
            return ComparisonStatus.NO_VALID_PRICES
        if selection.activation_conditions_unverified:
            return ComparisonStatus.PRICE_ONLY
        if any(entry.reason is not None for entry in difference.differences):
            return ComparisonStatus.PARTIAL
        return ComparisonStatus.COMPLETE
