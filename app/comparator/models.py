from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.parsers.models import ParsedOffer


@dataclass(slots=True, frozen=True)
class MarketplaceOffer:
    """Marketplace offer prepared for comparison workflows."""

    offer: ParsedOffer


@dataclass(slots=True, frozen=True)
class ProductComparisonInput:
    """Grouped marketplace offers for a single canonical product."""

    canonical_product_id: UUID | None
    offers: tuple[MarketplaceOffer, ...]
