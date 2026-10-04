from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid5

from app.matching.confidence import MatchDecision
from app.matching.service import MatchingService, MatchResult
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


@dataclass(slots=True, frozen=True, kw_only=True)
class CanonicalProductProposal:
    """System proposal to create a canonical product from an unmatched offer."""

    proposal_id: UUID
    offer: ParsedOffer
    proposed_name: str
    nearest_canonical_product: CanonicalProduct | None
    similarity: float


@dataclass(slots=True, frozen=True, kw_only=True)
class _UnresolvedOfferMatch:
    offer: ParsedOffer
    result: MatchResult


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
        matches = await self._load_unresolved_matches(tenant_id)
        candidates = [
            CanonicalOfferReviewCandidate(
                offer=match.offer,
                canonical_product=match.result.canonical_product,
                similarity=match.result.similarity,
                match_decision=match.result.decision,
            )
            for match in matches
            if match.result.decision is MatchDecision.REVIEW
            and match.result.canonical_product is not None
        ]
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

    async def list_product_proposals(
        self,
        tenant_id: UUID,
    ) -> tuple[CanonicalProductProposal, ...]:
        """Return stable system proposals for unmatched tenant offers."""
        matches = await self._load_unresolved_matches(tenant_id)
        proposals = [
            CanonicalProductProposal(
                proposal_id=_proposal_id(tenant_id, match.offer),
                offer=match.offer,
                proposed_name=" ".join((match.offer.title or "").split()),
                nearest_canonical_product=match.result.canonical_product,
                similarity=match.result.similarity,
            )
            for match in matches
            if match.result.decision is MatchDecision.NO_MATCH
        ]
        return tuple(
            sorted(
                proposals,
                key=lambda proposal: (
                    -proposal.similarity,
                    proposal.offer.marketplace,
                    proposal.offer.external_id or "",
                ),
            )
        )

    async def _load_unresolved_matches(
        self,
        tenant_id: UUID,
    ) -> tuple[_UnresolvedOfferMatch, ...]:
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
            matches: list[_UnresolvedOfferMatch] = []

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
                if result.decision is MatchDecision.AUTO_MATCH:
                    continue
                matches.append(
                    _UnresolvedOfferMatch(
                        offer=offer,
                        result=result,
                    )
                )
        return tuple(matches)


_PROPOSAL_NAMESPACE = UUID("3d000000-0000-4000-8000-000000000001")


def _proposal_id(tenant_id: UUID, offer: ParsedOffer) -> UUID:
    external_id = offer.external_id
    if external_id is None:
        raise ValueError("Product proposal requires an offer external ID.")
    identity = f"{tenant_id}:{offer.marketplace.strip().lower()}:{external_id.strip()}"
    return uuid5(_PROPOSAL_NAMESPACE, identity)
