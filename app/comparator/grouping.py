from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from app.comparator.models import MarketplaceOffer, ProductComparisonInput
from app.matching.confidence import MatchDecision
from app.matching.service import MatchingService
from app.models.canonical_product import CanonicalProduct


class OfferGroupingService:
    """Groups marketplace offers by canonical product using matching results."""

    def __init__(self, matching_service: MatchingService | None = None) -> None:
        """Initialize grouping with the existing matching service."""
        self._matching_service = matching_service or MatchingService()

    def group(
        self,
        offers: Sequence[MarketplaceOffer],
        candidates: Sequence[CanonicalProduct],
    ) -> list[ProductComparisonInput]:
        """Group offers by canonical product and keep unmatched offers separate."""
        grouped: dict[UUID, list[MarketplaceOffer]] = {}
        unmatched: list[ProductComparisonInput] = []

        for offer in offers:
            match_result = self._matching_service.match(offer.offer, candidates)
            canonical_product = match_result.canonical_product
            if (
                match_result.decision is MatchDecision.NO_MATCH
                or canonical_product is None
            ):
                unmatched.append(
                    ProductComparisonInput(
                        canonical_product_id=None,
                        offers=(offer,),
                    ),
                )
                continue

            grouped.setdefault(canonical_product.id, []).append(offer)

        result = [
            ProductComparisonInput(
                canonical_product_id=canonical_product_id,
                offers=tuple(items),
            )
            for canonical_product_id, items in grouped.items()
        ]
        result.extend(unmatched)
        return result
