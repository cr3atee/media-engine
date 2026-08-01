from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.auth import AdminPrincipal, require_admin
from app.api.dependencies import (
    get_admin_mutation_service,
    require_idempotency_key,
)
from app.api.errors import get_request_id
from app.api.schemas.admin_mutations import (
    AdminMutationResponse,
    ApproveContentRequest,
    PublicationCancelRequest,
    PublicationRetryRequest,
    RejectContentRequest,
    ResolveAmbiguousPublicationRequest,
)
from app.services.admin_mutations import (
    AdminCommandContext,
    AdminMutationResult,
    AdminMutationService,
    ContentReviewCommand,
    PublicationCommand,
    ResolvePublicationCommand,
)

router = APIRouter(prefix="/api/v1/admin", tags=["Admin mutations"])


@router.post(
    "/content/{content_id}/approve",
    response_model=AdminMutationResponse,
)
async def approve_content(
    request: Request,
    content_id: UUID,
    payload: ApproveContentRequest,
    principal: Annotated[AdminPrincipal, Depends(require_admin)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    service: Annotated[AdminMutationService, Depends(get_admin_mutation_service)],
) -> AdminMutationResponse:
    """Approve one generated content attempt through the command service."""
    result = await service.approve(
        ContentReviewCommand(
            content_id=content_id,
            expected_version=payload.expected_version,
            reason=payload.reason,
        ),
        _context(request, principal, idempotency_key),
    )
    return _response(result)


@router.post(
    "/content/{content_id}/reject",
    response_model=AdminMutationResponse,
)
async def reject_content(
    request: Request,
    content_id: UUID,
    payload: RejectContentRequest,
    principal: Annotated[AdminPrincipal, Depends(require_admin)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    service: Annotated[AdminMutationService, Depends(get_admin_mutation_service)],
) -> AdminMutationResponse:
    """Reject one generated content attempt through the command service."""
    result = await service.reject(
        ContentReviewCommand(
            content_id=content_id,
            expected_version=payload.expected_version,
            reason=payload.reason,
        ),
        _context(request, principal, idempotency_key),
    )
    return _response(result)


@router.post(
    "/publications/{publication_id}/retry",
    response_model=AdminMutationResponse,
)
async def retry_publication(
    request: Request,
    publication_id: UUID,
    payload: PublicationRetryRequest,
    principal: Annotated[AdminPrincipal, Depends(require_admin)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    service: Annotated[AdminMutationService, Depends(get_admin_mutation_service)],
) -> AdminMutationResponse:
    """Retry one known retryable publication without contacting its provider."""
    result = await service.retry(
        PublicationCommand(
            publication_id=publication_id,
            expected_version=payload.expected_version,
            reason=payload.reason,
        ),
        _context(request, principal, idempotency_key),
    )
    return _response(result)


@router.post(
    "/publications/{publication_id}/cancel",
    response_model=AdminMutationResponse,
)
async def cancel_publication(
    request: Request,
    publication_id: UUID,
    payload: PublicationCancelRequest,
    principal: Annotated[AdminPrincipal, Depends(require_admin)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    service: Annotated[AdminMutationService, Depends(get_admin_mutation_service)],
) -> AdminMutationResponse:
    """Cancel pending or retryable publication work."""
    result = await service.cancel(
        PublicationCommand(
            publication_id=publication_id,
            expected_version=payload.expected_version,
            reason=payload.reason,
        ),
        _context(request, principal, idempotency_key),
    )
    return _response(result)


@router.post(
    "/publications/{publication_id}/resolve-ambiguous",
    response_model=AdminMutationResponse,
)
async def resolve_ambiguous_publication(
    request: Request,
    publication_id: UUID,
    payload: ResolveAmbiguousPublicationRequest,
    principal: Annotated[AdminPrincipal, Depends(require_admin)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    service: Annotated[AdminMutationService, Depends(get_admin_mutation_service)],
) -> AdminMutationResponse:
    """Record an explicit operator decision for ambiguous delivery."""
    result = await service.resolve_ambiguous(
        ResolvePublicationCommand(
            publication_id=publication_id,
            expected_version=payload.expected_version,
            resolution=payload.resolution,
            reason=payload.reason,
            external_message_id=payload.external_message_id,
        ),
        _context(request, principal, idempotency_key),
    )
    return _response(result)


def _context(
    request: Request,
    principal: AdminPrincipal,
    idempotency_key: str,
) -> AdminCommandContext:
    return AdminCommandContext(
        actor_id=principal.actor_id,
        request_id=get_request_id(request),
        idempotency_key=idempotency_key,
    )


def _response(result: AdminMutationResult) -> AdminMutationResponse:
    return AdminMutationResponse(
        action_id=result.action_id,
        action=result.action,
        resource_type=result.resource_type,
        resource_id=result.resource_id,
        previous_state=result.previous_state,
        resulting_state=result.resulting_state,
        resulting_version=result.resulting_version,
        request_id=result.request_id,
        recorded_at=result.recorded_at,
        replayed=result.replayed,
    )
