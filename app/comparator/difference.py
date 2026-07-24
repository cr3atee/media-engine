from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.comparator.models import MarketplaceOffer, ProductComparisonInput
from app.comparator.selector import BestOfferSelection


@dataclass(slots=True, frozen=True)
class OfferDifference:
    """Price difference for a non-best offer inside one comparison group."""

    offer: MarketplaceOffer
    absolute_difference: Decimal | None
    percentage_difference: Decimal | None
    reason: str | None = None


@dataclass(slots=True, frozen=True)
class ComparisonDifferenceResult:
    """Comparison output for one grouped canonical product."""

    comparison: ProductComparisonInput
    best_offer: MarketplaceOffer | None
    differences: tuple[OfferDifference, ...]
    reason: str | None = None


class PriceDifferenceService:
    """Calculates price differences against the selected best offer."""

    def compare(self, selection: BestOfferSelection) -> ComparisonDifferenceResult:
        """Return price differences for all non-best offers in the group."""
        best_offer = selection.selected_offer
        if best_offer is None:
            return ComparisonDifferenceResult(
                comparison=selection.comparison,
                best_offer=None,
                differences=(),
                reason=selection.reason,
            )

        best_currency = best_offer.offer.currency
        best_price = best_offer.offer.price
        if best_currency is None or best_price is None:
            return ComparisonDifferenceResult(
                comparison=selection.comparison,
                best_offer=best_offer,
                differences=(),
                reason="best offer price unavailable",
            )

        differences: list[OfferDifference] = []
        for item in selection.comparison.offers:
            if item == best_offer:
                continue
            other_price = item.offer.price
            other_currency = item.offer.currency
            if other_price is None or other_currency is None:
                differences.append(
                    OfferDifference(
                        offer=item,
                        absolute_difference=None,
                        percentage_difference=None,
                        reason="price unavailable",
                    ),
                )
                continue
            if other_currency != best_currency:
                differences.append(
                    OfferDifference(
                        offer=item,
                        absolute_difference=None,
                        percentage_difference=None,
                        reason="currency mismatch",
                    ),
                )
                continue

            absolute_difference = other_price - best_price
            if best_price == Decimal("0"):
                differences.append(
                    OfferDifference(
                        offer=item,
                        absolute_difference=absolute_difference,
                        percentage_difference=None,
                        reason="best price is zero",
                    ),
                )
                continue

            percentage_difference = (absolute_difference / best_price) * Decimal("100")
            differences.append(
                OfferDifference(
                    offer=item,
                    absolute_difference=absolute_difference,
                    percentage_difference=percentage_difference,
                ),
            )

        return ComparisonDifferenceResult(
            comparison=selection.comparison,
            best_offer=best_offer,
            differences=tuple(differences),
            reason=selection.reason,
        )
