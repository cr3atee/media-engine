from __future__ import annotations

from collections.abc import Sequence

from app.comparator.models import MarketplaceOffer


def activation_comparison_reason(
    offers: Sequence[MarketplaceOffer], *, allow_unknown: bool = False
) -> str | None:
    """Keep strict defaults; price-only mode still rejects known conflicts."""
    if len(offers) < 2:
        return None
    conditions = tuple(item.offer.activation_conditions for item in offers)
    if not allow_unknown and any(condition is None for condition in conditions):
        return "activation conditions unknown"
    known = tuple(condition for condition in conditions if condition is not None)
    if known and any(condition != known[0] for condition in known[1:]):
        return "activation conditions mismatch"
    return None
