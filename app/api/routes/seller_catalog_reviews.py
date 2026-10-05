from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import (
    get_canonical_offer_review_queue_service,
    get_canonical_offer_review_service,
    get_canonical_product_proposal_service,
    require_idempotency_key,
    require_tenant_permission,
)
from app.api.errors import ApiError, get_request_id
from app.api.schemas.canonical_offer_reviews import (
    CanonicalOfferReviewCandidateResponse,
    CanonicalOfferReviewResponse,
    CanonicalProductProposalConfirmationResponse,
    CanonicalProductProposalResolutionResponse,
    CanonicalProductProposalResponse,
    ConfirmCanonicalOfferRequest,
    ConfirmCanonicalProductProposalRequest,
    RejectCanonicalOfferRequest,
    ResolveCanonicalProductProposalRequest,
)
from app.domain.admin_actions import AdminActorType
from app.domain.auth import Permission, TenantContext
from app.domain.canonical_offer_decisions import CanonicalOfferDecisionType
from app.matching.confidence import MatchDecision
from app.services.canonical_offer_linking import (
    CanonicalOfferLinkConflictError,
    CanonicalProductUnavailableError,
    MarketplaceOfferUnavailableError,
)
from app.services.canonical_offer_review import (
    CanonicalOfferActiveLinkConflictError,
    CanonicalOfferDecisionConflictError,
    CanonicalOfferReviewContext,
    CanonicalOfferReviewIdempotencyConflictError,
    CanonicalOfferReviewResult,
    CanonicalOfferReviewService,
    ReviewCanonicalOfferCommand,
)
from app.services.canonical_offer_review_queue import (
    CanonicalOfferReviewCandidate,
    CanonicalOfferReviewQueueService,
    CanonicalProductProposal,
)
from app.services.canonical_product_proposals import (
    CanonicalProductProposalConfirmationResult,
    CanonicalProductProposalConflictError,
    CanonicalProductProposalEvidenceRequiredError,
    CanonicalProductProposalResolutionResult,
    CanonicalProductProposalService,
    CanonicalProductProposalUnavailableError,
    ConfirmCanonicalProductProposalCommand,
    ResolveCanonicalProductProposalCommand,
)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/catalog",
    tags=["Seller catalog review"],
)

CatalogReviewTenant = Annotated[
    TenantContext,
    Depends(require_tenant_permission(Permission.CATALOG_REVIEW)),
]


@router.get(
    "/review-candidates",
    response_model=list[CanonicalOfferReviewCandidateResponse],
)
async def list_canonical_offer_review_candidates(
    context: CatalogReviewTenant,
    service: Annotated[
        CanonicalOfferReviewQueueService,
        Depends(get_canonical_offer_review_queue_service),
    ],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[CanonicalOfferReviewCandidateResponse]:
    """List unresolved review-confidence pairs for the authorized tenant."""
    candidates = await service.list_candidates(context.tenant.id)
    return [_candidate_response(candidate) for candidate in candidates[:limit]]


@router.get(
    "/product-proposals",
    response_model=list[CanonicalProductProposalResponse],
)
async def list_canonical_product_proposals(
    context: CatalogReviewTenant,
    service: Annotated[
        CanonicalOfferReviewQueueService,
        Depends(get_canonical_offer_review_queue_service),
    ],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[CanonicalProductProposalResponse]:
    """List system proposals derived from unmatched tenant offers."""
    proposals = await service.list_product_proposals(context.tenant.id)
    return [_proposal_response(proposal) for proposal in proposals[:limit]]


@router.post(
    "/product-proposals/{proposal_id}/confirm",
    response_model=CanonicalProductProposalConfirmationResponse,
)
async def confirm_canonical_product_proposal(
    request: Request,
    proposal_id: UUID,
    payload: ConfirmCanonicalProductProposalRequest,
    context: CatalogReviewTenant,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    service: Annotated[
        CanonicalProductProposalService,
        Depends(get_canonical_product_proposal_service),
    ],
) -> CanonicalProductProposalConfirmationResponse:
    """Atomically create and link one still-current system proposal."""
    try:
        result = await service.confirm(
            ConfirmCanonicalProductProposalCommand(
                tenant_id=context.tenant.id,
                proposal_id=proposal_id,
                marketplace=payload.marketplace,
                external_id=payload.external_id,
                reason=payload.reason,
            ),
            CanonicalOfferReviewContext(
                actor_id=str(context.principal.user_id),
                actor_type=AdminActorType.USER,
                request_id=get_request_id(request),
                idempotency_key=idempotency_key,
            ),
        )
    except MarketplaceOfferUnavailableError as exc:
        raise ApiError(
            404,
            "canonical_product_proposal_not_found",
            "Canonical product proposal was not found.",
        ) from exc
    except CanonicalProductProposalUnavailableError as exc:
        raise ApiError(
            409,
            "canonical_product_proposal_stale",
            "Canonical product proposal is no longer current.",
        ) from exc
    except CanonicalOfferReviewIdempotencyConflictError as exc:
        raise ApiError(
            409,
            "idempotency_conflict",
            "Idempotency key is bound to another catalog command.",
        ) from exc
    except (
        CanonicalProductProposalConflictError,
        CanonicalOfferDecisionConflictError,
        CanonicalOfferLinkConflictError,
    ) as exc:
        raise ApiError(
            409,
            "canonical_product_proposal_conflict",
            "Canonical product proposal conflicts with current catalog state.",
        ) from exc
    return _proposal_confirmation_response(result)


@router.post(
    "/product-proposals/{proposal_id}/resolve-existing",
    response_model=CanonicalProductProposalResolutionResponse,
)
async def resolve_canonical_product_proposal_to_existing(
    request: Request,
    proposal_id: UUID,
    payload: ResolveCanonicalProductProposalRequest,
    context: CatalogReviewTenant,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    service: Annotated[
        CanonicalProductProposalService,
        Depends(get_canonical_product_proposal_service),
    ],
) -> CanonicalProductProposalResolutionResponse:
    """Link one current proposal to its displayed nearest existing product."""
    try:
        result = await service.resolve_existing(
            ResolveCanonicalProductProposalCommand(
                tenant_id=context.tenant.id,
                proposal_id=proposal_id,
                marketplace=payload.marketplace,
                external_id=payload.external_id,
                canonical_product_id=payload.canonical_product_id,
                reason=payload.reason,
            ),
            CanonicalOfferReviewContext(
                actor_id=str(context.principal.user_id),
                actor_type=AdminActorType.USER,
                request_id=get_request_id(request),
                idempotency_key=idempotency_key,
            ),
        )
    except MarketplaceOfferUnavailableError as exc:
        raise ApiError(
            404,
            "canonical_product_proposal_not_found",
            "Canonical product proposal was not found.",
        ) from exc
    except CanonicalProductProposalEvidenceRequiredError as exc:
        raise ApiError(
            422,
            "canonical_product_proposal_evidence_required",
            "Existing-product resolution requires review evidence.",
        ) from exc
    except CanonicalProductProposalUnavailableError as exc:
        raise ApiError(
            409,
            "canonical_product_proposal_stale",
            "Canonical product proposal target is no longer current.",
        ) from exc
    except CanonicalOfferReviewIdempotencyConflictError as exc:
        raise ApiError(
            409,
            "idempotency_conflict",
            "Idempotency key is bound to another catalog command.",
        ) from exc
    except (
        CanonicalProductProposalConflictError,
        CanonicalOfferDecisionConflictError,
        CanonicalOfferLinkConflictError,
    ) as exc:
        raise ApiError(
            409,
            "canonical_product_proposal_conflict",
            "Canonical product proposal conflicts with current catalog state.",
        ) from exc
    return _proposal_resolution_response(result)


@router.post(
    "/reviews/confirm",
    response_model=CanonicalOfferReviewResponse,
)
async def confirm_canonical_offer(
    request: Request,
    payload: ConfirmCanonicalOfferRequest,
    context: CatalogReviewTenant,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    service: Annotated[
        CanonicalOfferReviewService,
        Depends(get_canonical_offer_review_service),
    ],
) -> CanonicalOfferReviewResponse:
    """Confirm one candidate and atomically persist its canonical link."""
    return await _review(
        request,
        payload.marketplace,
        payload.external_id,
        payload.canonical_product_id,
        payload.reason,
        CanonicalOfferDecisionType.CONFIRMED,
        context,
        idempotency_key,
        service,
    )


@router.post(
    "/reviews/reject",
    response_model=CanonicalOfferReviewResponse,
)
async def reject_canonical_offer(
    request: Request,
    payload: RejectCanonicalOfferRequest,
    context: CatalogReviewTenant,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    service: Annotated[
        CanonicalOfferReviewService,
        Depends(get_canonical_offer_review_service),
    ],
) -> CanonicalOfferReviewResponse:
    """Reject one candidate without changing the marketplace offer link."""
    return await _review(
        request,
        payload.marketplace,
        payload.external_id,
        payload.canonical_product_id,
        payload.reason,
        CanonicalOfferDecisionType.REJECTED,
        context,
        idempotency_key,
        service,
    )


async def _review(
    request: Request,
    marketplace: str,
    external_id: str,
    canonical_product_id: UUID,
    reason: str | None,
    decision: CanonicalOfferDecisionType,
    context: TenantContext,
    idempotency_key: str,
    service: CanonicalOfferReviewService,
) -> CanonicalOfferReviewResponse:
    try:
        result = await service.review(
            ReviewCanonicalOfferCommand(
                tenant_id=context.tenant.id,
                marketplace=marketplace,
                external_id=external_id,
                canonical_product_id=canonical_product_id,
                decision=decision,
                reason=reason,
            ),
            CanonicalOfferReviewContext(
                actor_id=str(context.principal.user_id),
                actor_type=AdminActorType.USER,
                request_id=get_request_id(request),
                idempotency_key=idempotency_key,
            ),
        )
    except (CanonicalProductUnavailableError, MarketplaceOfferUnavailableError) as exc:
        raise ApiError(
            404,
            "canonical_review_target_not_found",
            "Canonical review target was not found.",
        ) from exc
    except CanonicalOfferReviewIdempotencyConflictError as exc:
        raise ApiError(
            409,
            "idempotency_conflict",
            "Idempotency key is bound to another canonical review command.",
        ) from exc
    except CanonicalOfferDecisionConflictError as exc:
        raise ApiError(
            409,
            "canonical_offer_decision_conflict",
            "Canonical offer candidate already has a terminal decision.",
        ) from exc
    except (
        CanonicalOfferActiveLinkConflictError,
        CanonicalOfferLinkConflictError,
    ) as exc:
        raise ApiError(
            409,
            "canonical_offer_link_conflict",
            "Marketplace offer link conflicts with this review decision.",
        ) from exc
    return _review_response(result)


def _candidate_response(
    candidate: CanonicalOfferReviewCandidate,
) -> CanonicalOfferReviewCandidateResponse:
    offer = candidate.offer
    product = candidate.canonical_product
    if offer.external_id is None or offer.title is None:
        raise RuntimeError("Review candidate identity is incomplete.")
    return CanonicalOfferReviewCandidateResponse(
        marketplace=offer.marketplace,
        external_id=offer.external_id,
        offer_title=offer.title,
        offer_url=offer.url,
        offer_price=offer.price,
        currency=offer.currency,
        canonical_product_id=product.id,
        canonical_product_name=product.name,
        canonical_product_category=product.category,
        similarity=candidate.similarity,
        match_decision=candidate.match_decision,
    )


def _review_response(
    result: CanonicalOfferReviewResult,
) -> CanonicalOfferReviewResponse:
    decision = result.decision
    return CanonicalOfferReviewResponse(
        decision_id=decision.id,
        tenant_id=decision.tenant_id,
        marketplace=decision.marketplace,
        external_id=decision.external_id,
        canonical_product_id=decision.canonical_product_id,
        decision=decision.decision,
        actor_id=decision.actor_id,
        actor_type=decision.actor_type,
        reason=decision.reason,
        request_id=decision.request_id,
        created_at=decision.created_at,
        replayed=result.replayed,
    )


def _proposal_response(
    proposal: CanonicalProductProposal,
) -> CanonicalProductProposalResponse:
    offer = proposal.offer
    nearest = proposal.nearest_canonical_product
    if offer.external_id is None or offer.title is None:
        raise RuntimeError("Canonical product proposal identity is incomplete.")
    return CanonicalProductProposalResponse(
        proposal_id=proposal.proposal_id,
        marketplace=offer.marketplace,
        external_id=offer.external_id,
        offer_title=offer.title,
        offer_url=offer.url,
        offer_price=offer.price,
        currency=offer.currency,
        proposed_name=proposal.proposed_name,
        proposed_aliases=(),
        nearest_canonical_product_id=nearest.id if nearest is not None else None,
        nearest_canonical_product_name=nearest.name if nearest is not None else None,
        nearest_similarity=proposal.similarity,
        match_decision=MatchDecision.NO_MATCH,
    )


def _proposal_confirmation_response(
    result: CanonicalProductProposalConfirmationResult,
) -> CanonicalProductProposalConfirmationResponse:
    product = result.product
    decision = result.decision
    offer = result.offer
    if offer.external_id is None:
        raise RuntimeError("Confirmed proposal offer identity is incomplete.")
    return CanonicalProductProposalConfirmationResponse(
        proposal_id=result.proposal_id,
        canonical_product_id=product.id,
        canonical_product_name=product.name,
        canonical_product_category=product.category,
        canonical_product_aliases=product.aliases,
        marketplace=offer.marketplace,
        external_id=offer.external_id,
        decision_id=decision.id,
        decision=decision.decision,
        created_at=decision.created_at,
        replayed=result.replayed,
    )


def _proposal_resolution_response(
    result: CanonicalProductProposalResolutionResult,
) -> CanonicalProductProposalResolutionResponse:
    product = result.product
    decision = result.decision
    offer = result.offer
    if offer.external_id is None:
        raise RuntimeError("Resolved proposal offer identity is incomplete.")
    return CanonicalProductProposalResolutionResponse(
        proposal_id=result.proposal_id,
        canonical_product_id=product.id,
        canonical_product_name=product.name,
        canonical_product_category=product.category,
        canonical_product_aliases=product.aliases,
        marketplace=offer.marketplace,
        external_id=offer.external_id,
        decision_id=decision.id,
        decision=decision.decision,
        created_at=decision.created_at,
        replayed=result.replayed,
    )
