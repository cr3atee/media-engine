from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.matching.confidence import MatchDecision
from app.matching.service import MatchingService
from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer
from app.services.repository_scope import RepositoryScopeFactory


@dataclass(slots=True, frozen=True, kw_only=True)
class CanonicalOfferReviewCandidate:
    """One deterministic offer/product pair requiring human review."""

    offer: ParsedOffer
    canonical_product: CanonicalProduct
    similarity: float
    match_decision: MatchDecision


class CanonicalOfferReviewQueueService:
    """Build a tenant-scoped queue from existing deterministic matching rules."""

    def __init__(
        self,
        repository_scope_factory: RepositoryScopeFactory,
        *,
        matching_service: MatchingService | None = None,
    ) -> None:
        self._repository_scope_factory = repository_scope_factory
        self._matching_service = matching_service or MatchingService()

    async def list_candidates(
        self,
        tenant_id: UUID,
    ) -> tuple[CanonicalOfferReviewCandidate, ...]:
        """Return unresolved review-confidence candidates for one tenant."""
        async with self._repository_scope_factory() as repositories:
            offers = await repositories.offers.list_by_tenant(tenant_id)
            products = tuple(
                await repositories.canonical_products.list_by_tenant(tenant_id)
            )
            decisions = await repositories.canonical_offer_decisions.list_by_tenant(
                tenant_id
            )
            decided_product_ids_by_offer: dict[tuple[str, str], set[UUID]] = {}
            for decision in decisions:
                offer_key = (decision.marketplace, decision.external_id)
                decided_product_ids_by_offer.setdefault(offer_key, set()).add(
                    decision.canonical_product_id
                )
            candidates: list[CanonicalOfferReviewCandidate] = []

            for offer in offers:
                if (
                    offer.canonical_product_id is not None
                    or offer.external_id is None
                    or not offer.title
                ):
                    continue
                offer_key = (
                    offer.marketplace.strip().lower(),
                    offer.external_id.strip(),
                )
                decided_product_ids = decided_product_ids_by_offer.get(offer_key, set())
                eligible_products = tuple(
                    product
                    for product in products
                    if product.id not in decided_product_ids
                )
                result = self._matching_service.match(offer, eligible_products)
                if (
                    result.decision is not MatchDecision.REVIEW
                    or result.canonical_product is None
                ):
                    continue
                candidates.append(
                    CanonicalOfferReviewCandidate(
                        offer=offer,
                        canonical_product=result.canonical_product,
                        similarity=result.similarity,
                        match_decision=result.decision,
                    )
                )

        return tuple(
            sorted(
                candidates,
                key=lambda candidate: (
                    -candidate.similarity,
                    candidate.offer.marketplace,
                    candidate.offer.external_id or "",
                    candidate.canonical_product.id.hex,
                ),
            )
        )
