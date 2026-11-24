from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.comparator.activation import activation_comparison_reason
from app.comparator.models import MarketplaceOffer, ProductComparisonInput


@dataclass(slots=True, frozen=True)
class BestOfferSelection:
    """Result of selecting the best offer within one comparison group."""

    comparison: ProductComparisonInput
    selected_offer: MarketplaceOffer | None
    reason: str
    currency_mismatch: bool = False
    activation_conditions_unverified: bool = False


class BestOfferSelector:
    """Selects the cheapest valid offer within a grouped comparison."""

    def select(
        self,
        comparison: ProductComparisonInput,
        *,
        require_activation_conditions: bool = True,
        allow_unknown_activation_conditions: bool = False,
    ) -> BestOfferSelection:
        """Select strictly by default; allow marked price-only results explicitly."""
        valid_offers = [
            item
            for item in comparison.offers
            if item.offer.price is not None and item.offer.currency is not None
        ]
        if not valid_offers:
            return BestOfferSelection(
                comparison=comparison,
                selected_offer=None,
                reason="no valid prices",
            )

        currencies = {item.offer.currency for item in valid_offers}
        if len(currencies) > 1:
            return BestOfferSelection(
                comparison=comparison,
                selected_offer=None,
                reason="currency mismatch",
                currency_mismatch=True,
            )

        unverified = False
        if require_activation_conditions and (
            len(valid_offers) > 1 or allow_unknown_activation_conditions
        ):
            reason = activation_comparison_reason(
                comparison.offers, allow_unknown=allow_unknown_activation_conditions
            )
            if reason is not None:
                return BestOfferSelection(
                    comparison=comparison, selected_offer=None, reason=reason
                )
            unverified = (
                allow_unknown_activation_conditions
                and len(comparison.offers) > 1
                and any(
                    item.offer.activation_conditions is None
                    for item in comparison.offers
                )
            )

        if len(valid_offers) == 1:
            return BestOfferSelection(
                comparison=comparison,
                selected_offer=valid_offers[0],
                reason="only one offer",
                activation_conditions_unverified=unverified,
            )

        selected_offer = min(
            valid_offers,
            key=self._selection_key,
        )
        return BestOfferSelection(
            comparison=comparison,
            selected_offer=selected_offer,
            reason="lowest price",
            activation_conditions_unverified=unverified,
        )

    def _selection_key(self, item: MarketplaceOffer) -> tuple[Decimal, str, str, str]:
        """Return a deterministic ordering key for tie-breaking among offers."""
        assert item.offer.price is not None
        assert item.offer.currency is not None
        return (
            item.offer.price,
            item.offer.currency,
            item.offer.marketplace,
            item.offer.external_id or "",
        )
