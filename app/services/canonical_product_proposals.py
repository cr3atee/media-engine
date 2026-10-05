from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domain.canonical_offer_decisions import (
    CanonicalOfferDecision,
    CanonicalOfferDecisionType,
    build_canonical_offer_decision_fingerprint,
)
from app.matching.confidence import MatchDecision
from app.matching.service import MatchingService
from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer
from app.repositories.provider import RepositoryProvider
from app.services.canonical_offer_linking import (
    LinkCanonicalOfferCommand,
    MarketplaceOfferUnavailableError,
    link_canonical_offer,
)
from app.services.canonical_offer_review import (
    CanonicalOfferDecisionConflictError,
    CanonicalOfferReviewContext,
    CanonicalOfferReviewIdempotencyConflictError,
)
from app.services.canonical_offer_review_queue import (
    CanonicalProductProposal,
    build_canonical_product_proposal,
    canonical_product_proposal_id,
    resolve_unreviewed_offer_match,
)
from app.services.repository_scope import RepositoryScopeFactory


@dataclass(slots=True, frozen=True, kw_only=True)
class ConfirmCanonicalProductProposalCommand:
    """Confirm one current system proposal for an existing source offer."""

    tenant_id: UUID
    proposal_id: UUID
    marketplace: str
    external_id: str
    reason: str | None = None


@dataclass(slots=True, frozen=True, kw_only=True)
class ResolveCanonicalProductProposalCommand:
    """Resolve one current proposal to its nearest canonical product."""

    tenant_id: UUID
    proposal_id: UUID
    marketplace: str
    external_id: str
    canonical_product_id: UUID
    reason: str


@dataclass(slots=True, frozen=True, kw_only=True)
class CanonicalProductProposalConfirmationResult:
    """Atomically created product, linked offer, and immutable evidence."""

    proposal_id: UUID
    product: CanonicalProduct
    offer: ParsedOffer
    decision: CanonicalOfferDecision
    replayed: bool


@dataclass(slots=True, frozen=True, kw_only=True)
class CanonicalProductProposalResolutionResult:
    """Existing product link and immutable human resolution evidence."""

    proposal_id: UUID
    product: CanonicalProduct
    offer: ParsedOffer
    decision: CanonicalOfferDecision
    replayed: bool


class CanonicalProductProposalError(Exception):
    """Base failure for canonical-product proposal confirmation."""


class CanonicalProductProposalUnavailableError(CanonicalProductProposalError):
    """Raised when the requested proposal is absent or no longer current."""


class CanonicalProductProposalConflictError(CanonicalProductProposalError):
    """Raised when current catalog state prevents proposal confirmation."""


class CanonicalProductProposalEvidenceRequiredError(CanonicalProductProposalError):
    """Raised when an explicit existing-product resolution lacks evidence."""


class CanonicalProductProposalService:
    """Apply explicit source-backed proposal decisions transactionally."""

    def __init__(
        self,
        repository_scope_factory: RepositoryScopeFactory,
        *,
        matching_service: MatchingService | None = None,
        clock: Callable[[], datetime] | None = None,
        decision_id_factory: Callable[[], UUID] | None = None,
    ) -> None:
        self._repository_scope_factory = repository_scope_factory
        self._matching_service = matching_service or MatchingService()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._decision_id_factory = decision_id_factory or uuid4

    async def confirm(
        self,
        command: ConfirmCanonicalProductProposalCommand,
        context: CanonicalOfferReviewContext,
    ) -> CanonicalProductProposalConfirmationResult:
        """Create, link, and audit one still-current no-match proposal."""
        marketplace = command.marketplace.strip().lower()
        external_id = command.external_id.strip()
        fingerprint = build_canonical_offer_decision_fingerprint(
            tenant_id=command.tenant_id,
            marketplace=marketplace,
            external_id=external_id,
            canonical_product_id=command.proposal_id,
            decision=CanonicalOfferDecisionType.CONFIRMED,
            actor_id=context.actor_id,
            actor_type=context.actor_type,
            reason=command.reason,
        )
        async with self._repository_scope_factory() as repositories:
            decisions = repositories.canonical_offer_decisions
            await decisions.acquire_idempotency_lock(
                command.tenant_id,
                context.idempotency_key,
            )
            existing_replay = await decisions.get_by_idempotency_key(
                command.tenant_id,
                context.idempotency_key,
            )
            if existing_replay is not None:
                if existing_replay.request_fingerprint != fingerprint:
                    raise CanonicalOfferReviewIdempotencyConflictError(
                        "Idempotency key is bound to another catalog command."
                    )
                return await _load_replay(
                    repositories,
                    command,
                    existing_replay,
                )

            await decisions.acquire_offer_lock(
                command.tenant_id,
                marketplace,
                external_id,
            )
            await decisions.acquire_pair_lock(
                command.tenant_id,
                marketplace,
                external_id,
                command.proposal_id,
            )
            existing_pair = await decisions.get_for_pair(
                command.tenant_id,
                marketplace,
                external_id,
                command.proposal_id,
            )
            if existing_pair is not None:
                raise CanonicalOfferDecisionConflictError(
                    "Canonical product proposal already has a terminal decision."
                )

            proposal = await _load_current_proposal(
                repositories,
                tenant_id=command.tenant_id,
                proposal_id=command.proposal_id,
                marketplace=marketplace,
                external_id=external_id,
                matching_service=self._matching_service,
            )
            if len(proposal.proposed_name) > 255:
                raise CanonicalProductProposalUnavailableError(
                    "Canonical product proposal name exceeds storage limits."
                )
            if await repositories.canonical_products.get_by_id(command.proposal_id):
                raise CanonicalProductProposalConflictError(
                    "Canonical product proposal identity is already in use."
                )

            product = CanonicalProduct(
                id=command.proposal_id,
                tenant_id=command.tenant_id,
                name=proposal.proposed_name,
                category=None,
                aliases=(),
            )
            await repositories.canonical_products.save(product)
            linked_offer, stored_decision = await _link_and_record_decision(
                repositories,
                tenant_id=command.tenant_id,
                marketplace=marketplace,
                external_id=external_id,
                canonical_product_id=product.id,
                context=context,
                fingerprint=fingerprint,
                reason=command.reason,
                clock=self._clock,
                decision_id_factory=self._decision_id_factory,
            )
            return CanonicalProductProposalConfirmationResult(
                proposal_id=proposal.proposal_id,
                product=product,
                offer=linked_offer,
                decision=stored_decision,
                replayed=False,
            )

    async def resolve_existing(
        self,
        command: ResolveCanonicalProductProposalCommand,
        context: CanonicalOfferReviewContext,
    ) -> CanonicalProductProposalResolutionResult:
        """Link a current no-match proposal to its displayed nearest product."""
        if not command.reason.strip():
            raise CanonicalProductProposalEvidenceRequiredError(
                "Existing-product resolution requires review evidence."
            )
        marketplace = command.marketplace.strip().lower()
        external_id = command.external_id.strip()
        fingerprint = build_canonical_offer_decision_fingerprint(
            tenant_id=command.tenant_id,
            marketplace=marketplace,
            external_id=external_id,
            canonical_product_id=command.canonical_product_id,
            decision=CanonicalOfferDecisionType.CONFIRMED,
            actor_id=context.actor_id,
            actor_type=context.actor_type,
            reason=command.reason,
        )
        async with self._repository_scope_factory() as repositories:
            decisions = repositories.canonical_offer_decisions
            await decisions.acquire_idempotency_lock(
                command.tenant_id,
                context.idempotency_key,
            )
            existing_replay = await decisions.get_by_idempotency_key(
                command.tenant_id,
                context.idempotency_key,
            )
            if existing_replay is not None:
                if existing_replay.request_fingerprint != fingerprint:
                    raise CanonicalOfferReviewIdempotencyConflictError(
                        "Idempotency key is bound to another catalog command."
                    )
                return await _load_resolution_replay(
                    repositories,
                    command,
                    existing_replay,
                )

            await decisions.acquire_offer_lock(
                command.tenant_id,
                marketplace,
                external_id,
            )
            await decisions.acquire_pair_lock(
                command.tenant_id,
                marketplace,
                external_id,
                command.canonical_product_id,
            )
            existing_pair = await decisions.get_for_pair(
                command.tenant_id,
                marketplace,
                external_id,
                command.canonical_product_id,
            )
            if existing_pair is not None:
                raise CanonicalOfferDecisionConflictError(
                    "Canonical product proposal already has a terminal decision."
                )

            proposal = await _load_current_proposal(
                repositories,
                tenant_id=command.tenant_id,
                proposal_id=command.proposal_id,
                marketplace=marketplace,
                external_id=external_id,
                matching_service=self._matching_service,
            )
            product = proposal.nearest_canonical_product
            if product is None or product.id != command.canonical_product_id:
                raise CanonicalProductProposalUnavailableError(
                    "Canonical product proposal target is no longer current."
                )

            linked_offer, stored_decision = await _link_and_record_decision(
                repositories,
                tenant_id=command.tenant_id,
                marketplace=marketplace,
                external_id=external_id,
                canonical_product_id=product.id,
                context=context,
                fingerprint=fingerprint,
                reason=command.reason,
                clock=self._clock,
                decision_id_factory=self._decision_id_factory,
            )
            return CanonicalProductProposalResolutionResult(
                proposal_id=proposal.proposal_id,
                product=product,
                offer=linked_offer,
                decision=stored_decision,
                replayed=False,
            )


async def _load_current_proposal(
    repositories: RepositoryProvider,
    *,
    tenant_id: UUID,
    proposal_id: UUID,
    marketplace: str,
    external_id: str,
    matching_service: MatchingService,
) -> CanonicalProductProposal:
    offer = await repositories.offers.get_by_identity(
        tenant_id,
        marketplace,
        external_id,
    )
    if offer is None:
        raise MarketplaceOfferUnavailableError(
            "Marketplace offer is unavailable for this tenant."
        )
    if offer.canonical_product_id is not None:
        raise CanonicalProductProposalConflictError(
            "Marketplace offer is already linked to a canonical product."
        )
    expected_id = canonical_product_proposal_id(tenant_id, offer)
    if expected_id != proposal_id:
        raise CanonicalProductProposalUnavailableError(
            "Canonical product proposal is unavailable."
        )

    products = tuple(await repositories.canonical_products.list_by_tenant(tenant_id))
    decisions = await repositories.canonical_offer_decisions.list_for_offer(
        tenant_id,
        marketplace,
        external_id,
    )
    result = resolve_unreviewed_offer_match(
        offer,
        products,
        {decision.canonical_product_id for decision in decisions},
        matching_service,
    )
    if result is None or result.decision is not MatchDecision.NO_MATCH:
        raise CanonicalProductProposalUnavailableError(
            "Canonical product proposal is no longer eligible."
        )
    proposal = build_canonical_product_proposal(
        tenant_id,
        offer,
        result,
    )
    if proposal is None:
        raise CanonicalProductProposalUnavailableError(
            "Canonical product proposal is no longer eligible."
        )
    return proposal


async def _link_and_record_decision(
    repositories: RepositoryProvider,
    *,
    tenant_id: UUID,
    marketplace: str,
    external_id: str,
    canonical_product_id: UUID,
    context: CanonicalOfferReviewContext,
    fingerprint: str,
    reason: str | None,
    clock: Callable[[], datetime],
    decision_id_factory: Callable[[], UUID],
) -> tuple[ParsedOffer, CanonicalOfferDecision]:
    linked_offer = await link_canonical_offer(
        repositories,
        LinkCanonicalOfferCommand(
            tenant_id=tenant_id,
            canonical_product_id=canonical_product_id,
            marketplace=marketplace,
            external_id=external_id,
        ),
    )
    decision = CanonicalOfferDecision(
        id=decision_id_factory(),
        tenant_id=tenant_id,
        marketplace=marketplace,
        external_id=external_id,
        canonical_product_id=canonical_product_id,
        decision=CanonicalOfferDecisionType.CONFIRMED,
        actor_id=context.actor_id,
        actor_type=context.actor_type,
        request_id=context.request_id,
        idempotency_key=context.idempotency_key,
        request_fingerprint=fingerprint,
        reason=reason,
        created_at=clock(),
    )
    return linked_offer, await repositories.canonical_offer_decisions.append(decision)


async def _load_replay(
    repositories: RepositoryProvider,
    command: ConfirmCanonicalProductProposalCommand,
    decision: CanonicalOfferDecision,
) -> CanonicalProductProposalConfirmationResult:
    product = await repositories.canonical_products.get_by_tenant_and_id(
        command.tenant_id,
        decision.canonical_product_id,
    )
    offer = await repositories.offers.get_by_identity(
        command.tenant_id,
        command.marketplace.strip().lower(),
        command.external_id.strip(),
    )
    if (
        product is None
        or offer is None
        or offer.canonical_product_id != product.id
        or decision.decision is not CanonicalOfferDecisionType.CONFIRMED
        or decision.canonical_product_id != command.proposal_id
    ):
        raise CanonicalProductProposalConflictError(
            "Persisted proposal confirmation state is inconsistent."
        )
    return CanonicalProductProposalConfirmationResult(
        proposal_id=command.proposal_id,
        product=product,
        offer=offer,
        decision=decision,
        replayed=True,
    )


async def _load_resolution_replay(
    repositories: RepositoryProvider,
    command: ResolveCanonicalProductProposalCommand,
    decision: CanonicalOfferDecision,
) -> CanonicalProductProposalResolutionResult:
    product = await repositories.canonical_products.get_by_tenant_and_id(
        command.tenant_id,
        command.canonical_product_id,
    )
    offer = await repositories.offers.get_by_identity(
        command.tenant_id,
        command.marketplace.strip().lower(),
        command.external_id.strip(),
    )
    if (
        product is None
        or offer is None
        or offer.canonical_product_id != product.id
        or decision.decision is not CanonicalOfferDecisionType.CONFIRMED
        or decision.canonical_product_id != command.canonical_product_id
        or canonical_product_proposal_id(command.tenant_id, offer)
        != command.proposal_id
    ):
        raise CanonicalProductProposalConflictError(
            "Persisted proposal resolution state is inconsistent."
        )
    return CanonicalProductProposalResolutionResult(
        proposal_id=command.proposal_id,
        product=product,
        offer=offer,
        decision=decision,
        replayed=True,
    )
