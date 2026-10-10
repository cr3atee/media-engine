from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Sequence
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
class MarketplaceCatalogOnboardingSummary:
    """Catalog onboarding counts for one marketplace."""

    marketplace: str
    total_offers: int
    linked_offers: int
    unresolved_offers: int
    review_candidates: int
    product_proposals: int
    unqueued_offers: int


@dataclass(slots=True, frozen=True, kw_only=True)
class CatalogOnboardingSummary:
    """Tenant-scoped progress across the guarded catalog onboarding flow."""

    total_offers: int
    linked_offers: int
    unresolved_offers: int
    review_candidates: int
    product_proposals: int
    unqueued_offers: int
    canonical_products: int
    terminal_decisions: int
    marketplaces: tuple[MarketplaceCatalogOnboardingSummary, ...]


@dataclass(slots=True, frozen=True, kw_only=True)
class CatalogOnboardingWorkspace:
    """One consistent tenant-scoped snapshot for the review workspace."""

    summary: CatalogOnboardingSummary
    review_candidates: tuple[CanonicalOfferReviewCandidate, ...]
    product_proposals: tuple[CanonicalProductProposal, ...]


@dataclass(slots=True, frozen=True, kw_only=True)
class _UnresolvedOfferMatch:
    offer: ParsedOffer
    result: MatchResult


@dataclass(slots=True, frozen=True, kw_only=True)
class _CatalogReviewState:
    offers: tuple[ParsedOffer, ...]
    products: tuple[CanonicalProduct, ...]
    decided_product_ids_by_offer: dict[tuple[str, str], set[UUID]]
    terminal_decisions: int


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
        return _build_review_candidates(matches)

    async def list_product_proposals(
        self,
        tenant_id: UUID,
    ) -> tuple[CanonicalProductProposal, ...]:
        """Return stable system proposals for unmatched tenant offers."""
        matches = await self._load_unresolved_matches(tenant_id)
        return _build_product_proposals(tenant_id, matches)

    async def get_onboarding_summary(
        self,
        tenant_id: UUID,
    ) -> CatalogOnboardingSummary:
        """Return complete queue and linkage progress for one tenant."""
        state = await self._load_state(tenant_id)
        matches = _resolve_unresolved_matches(state, self._matching_service)
        return _build_onboarding_summary(state, matches)

    async def get_onboarding_workspace(
        self,
        tenant_id: UUID,
    ) -> CatalogOnboardingWorkspace:
        """Load summary and both queues from one consistent repository state."""
        state = await self._load_state(tenant_id)
        matches = _resolve_unresolved_matches(state, self._matching_service)
        return CatalogOnboardingWorkspace(
            summary=_build_onboarding_summary(state, matches),
            review_candidates=_build_review_candidates(matches),
            product_proposals=_build_product_proposals(tenant_id, matches),
        )

    async def _load_unresolved_matches(
        self,
        tenant_id: UUID,
    ) -> tuple[_UnresolvedOfferMatch, ...]:
        state = await self._load_state(tenant_id)
        return _resolve_unresolved_matches(state, self._matching_service)

    async def _load_state(self, tenant_id: UUID) -> _CatalogReviewState:
        async with self._repository_scope_factory() as repositories:
            offers = tuple(await repositories.offers.list_by_tenant(tenant_id))
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
        return _CatalogReviewState(
            offers=offers,
            products=products,
            decided_product_ids_by_offer=decided_product_ids_by_offer,
            terminal_decisions=len(decisions),
        )


def _resolve_unresolved_matches(
    state: _CatalogReviewState,
    matching_service: MatchingService,
) -> tuple[_UnresolvedOfferMatch, ...]:
    matches: list[_UnresolvedOfferMatch] = []
    for offer in state.offers:
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
        result = resolve_unreviewed_offer_match(
            offer,
            state.products,
            state.decided_product_ids_by_offer.get(offer_key, set()),
            matching_service,
        )
        if result is not None:
            matches.append(_UnresolvedOfferMatch(offer=offer, result=result))
    return tuple(matches)


def _build_review_candidates(
    matches: Sequence[_UnresolvedOfferMatch],
) -> tuple[CanonicalOfferReviewCandidate, ...]:
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


def _build_product_proposals(
    tenant_id: UUID,
    matches: Sequence[_UnresolvedOfferMatch],
) -> tuple[CanonicalProductProposal, ...]:
    proposals = [
        proposal
        for match in matches
        if (
            proposal := build_canonical_product_proposal(
                tenant_id,
                match.offer,
                match.result,
            )
        )
        is not None
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


def _build_onboarding_summary(
    state: _CatalogReviewState,
    matches: Sequence[_UnresolvedOfferMatch],
) -> CatalogOnboardingSummary:
    total_by_marketplace: Counter[str] = Counter()
    linked_by_marketplace: Counter[str] = Counter()
    review_by_marketplace: Counter[str] = Counter()
    proposal_by_marketplace: Counter[str] = Counter()

    for offer in state.offers:
        marketplace = offer.marketplace.strip().lower()
        total_by_marketplace[marketplace] += 1
        if offer.canonical_product_id is not None:
            linked_by_marketplace[marketplace] += 1

    for match in matches:
        marketplace = match.offer.marketplace.strip().lower()
        if match.result.decision is MatchDecision.REVIEW:
            review_by_marketplace[marketplace] += 1
        elif match.result.decision is MatchDecision.NO_MATCH:
            proposal_by_marketplace[marketplace] += 1

    marketplaces: list[MarketplaceCatalogOnboardingSummary] = []
    for marketplace in sorted(total_by_marketplace):
        total = total_by_marketplace[marketplace]
        linked = linked_by_marketplace[marketplace]
        unresolved = total - linked
        reviews = review_by_marketplace[marketplace]
        proposals = proposal_by_marketplace[marketplace]
        marketplaces.append(
            MarketplaceCatalogOnboardingSummary(
                marketplace=marketplace,
                total_offers=total,
                linked_offers=linked,
                unresolved_offers=unresolved,
                review_candidates=reviews,
                product_proposals=proposals,
                unqueued_offers=unresolved - reviews - proposals,
            )
        )

    linked_offers = sum(linked_by_marketplace.values())
    review_candidates = sum(review_by_marketplace.values())
    product_proposals = sum(proposal_by_marketplace.values())
    unresolved_offers = len(state.offers) - linked_offers
    return CatalogOnboardingSummary(
        total_offers=len(state.offers),
        linked_offers=linked_offers,
        unresolved_offers=unresolved_offers,
        review_candidates=review_candidates,
        product_proposals=product_proposals,
        unqueued_offers=(unresolved_offers - review_candidates - product_proposals),
        canonical_products=len(state.products),
        terminal_decisions=state.terminal_decisions,
        marketplaces=tuple(marketplaces),
    )


_PROPOSAL_NAMESPACE = UUID("3d000000-0000-4000-8000-000000000001")


def resolve_unreviewed_offer_match(
    offer: ParsedOffer,
    products: Sequence[CanonicalProduct],
    terminal_product_ids: Collection[UUID],
    matching_service: MatchingService,
) -> MatchResult | None:
    """Match one eligible unlinked offer after excluding terminal pairs."""
    if (
        offer.canonical_product_id is not None
        or offer.external_id is None
        or not offer.title
    ):
        return None
    eligible_products = tuple(
        product for product in products if product.id not in terminal_product_ids
    )
    return matching_service.match(offer, eligible_products)


def build_canonical_product_proposal(
    tenant_id: UUID,
    offer: ParsedOffer,
    result: MatchResult,
) -> CanonicalProductProposal | None:
    """Project one current no-match result into a stable read-only proposal."""
    if result.decision is not MatchDecision.NO_MATCH:
        return None
    return CanonicalProductProposal(
        proposal_id=canonical_product_proposal_id(tenant_id, offer),
        offer=offer,
        proposed_name=" ".join((offer.title or "").split()),
        nearest_canonical_product=result.canonical_product,
        similarity=result.similarity,
    )


def canonical_product_proposal_id(tenant_id: UUID, offer: ParsedOffer) -> UUID:
    """Return the stable proposal identity for one tenant-owned source offer."""
    external_id = offer.external_id
    if external_id is None:
        raise ValueError("Product proposal requires an offer external ID.")
    identity = f"{tenant_id}:{offer.marketplace.strip().lower()}:{external_id.strip()}"
    return uuid5(_PROPOSAL_NAMESPACE, identity)
