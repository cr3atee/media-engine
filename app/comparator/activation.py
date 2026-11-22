from __future__ import annotations

from collections.abc import Sequence

from app.comparator.models import MarketplaceOffer


def activation_comparison_reason(offers: Sequence[MarketplaceOffer]) -> str | None:
    """Reject unknown/different terms before treating prices as comparable."""
    if len(offers) < 2:
        return None
    conditions = tuple(item.offer.activation_conditions for item in offers)
    if any(condition is None for condition in conditions):
        return "activation conditions unknown"
    if any(condition != conditions[0] for condition in conditions[1:]):
        return "activation conditions mismatch"
    return None
