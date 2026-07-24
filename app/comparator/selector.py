from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.comparator.models import MarketplaceOffer, ProductComparisonInput


@dataclass(slots=True, frozen=True)
class BestOfferSelection:
    """Result of selecting the best offer within one comparison group."""

    comparison: ProductComparisonInput
    selected_offer: MarketplaceOffer | None
    reason: str
    currency_mismatch: bool = False


class BestOfferSelector:
    """Selects the cheapest valid offer within a grouped comparison."""

    def select(self, comparison: ProductComparisonInput) -> BestOfferSelection:
        """Return the best offer for a grouped comparison input."""
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

        if len(valid_offers) == 1:
            return BestOfferSelection(
                comparison=comparison,
                selected_offer=valid_offers[0],
                reason="only one offer",
            )

        selected_offer = min(
            valid_offers,
            key=self._selection_key,
        )
        return BestOfferSelection(
            comparison=comparison,
            selected_offer=selected_offer,
            reason="lowest price",
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
