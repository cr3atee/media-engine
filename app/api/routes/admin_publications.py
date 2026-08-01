from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.auth import AdminPrincipal, require_admin
from app.api.dependencies import get_publication_query_service
from app.api.errors import ApiError
from app.api.mappers import publication_response
from app.api.routes.helpers import enum_value, next_cursor, page_request
from app.api.schemas.common import PageResponse
from app.api.schemas.publications import (
    PublicationQueryParams,
    PublicationResponse,
)
from app.repositories.queries.models import PublicationQuery
from app.services.admin_queries import AdminPublicationQueryService

router = APIRouter(prefix="/api/v1/admin/publications", tags=["Publications"])
event_publication_router = APIRouter(
    prefix="/api/v1/admin/events",
    tags=["Publications"],
)


@router.get("", response_model=PageResponse[PublicationResponse])
async def list_publications(
    request: Request,
    params: Annotated[PublicationQueryParams, Depends()],
    _principal: Annotated[AdminPrincipal, Depends(require_admin)],
    service: Annotated[
        AdminPublicationQueryService,
        Depends(get_publication_query_service),
    ],
) -> PageResponse[PublicationResponse]:
    """List publication intents and safe delivery state."""
    page = page_request(request, resource="publications", params=params)
    result = await service.list_publications(_publication_query(params), page)
    return PageResponse(
        items=[publication_response(item) for item in result.items],
        next_cursor=next_cursor(request, position=result.next_cursor),
        page_size=page.limit,
    )


@router.get("/{publication_id}", response_model=PublicationResponse)
async def get_publication(
    publication_id: UUID,
    _principal: Annotated[AdminPrincipal, Depends(require_admin)],
    service: Annotated[
        AdminPublicationQueryService,
        Depends(get_publication_query_service),
    ],
) -> PublicationResponse:
    """Return one publication intent and safe delivery state."""
    publication = await service.get_publication(publication_id)
    if publication is None:
        raise ApiError(404, "not_found", "Publication was not found.")
    return publication_response(publication)


@event_publication_router.get(
    "/{event_id}/publications",
    response_model=PageResponse[PublicationResponse],
)
async def list_event_publications(
    request: Request,
    event_id: UUID,
    params: Annotated[PublicationQueryParams, Depends()],
    _principal: Annotated[AdminPrincipal, Depends(require_admin)],
    service: Annotated[
        AdminPublicationQueryService,
        Depends(get_publication_query_service),
    ],
) -> PageResponse[PublicationResponse]:
    """List publications related to one event."""
    scoped = params.model_copy(update={"event_id": event_id})
    page = page_request(request, resource="publications", params=scoped)
    result = await service.list_publications(_publication_query(scoped), page)
    return PageResponse(
        items=[publication_response(item) for item in result.items],
        next_cursor=next_cursor(request, position=result.next_cursor),
        page_size=page.limit,
    )


def _publication_query(params: PublicationQueryParams) -> PublicationQuery:
    return PublicationQuery(
        event_id=params.event_id,
        content_id=params.content_id,
        channel=params.channel,
        status=enum_value(params.status),
        retryable=params.retryable,
        permanent_failure=params.permanent_failure,
        ambiguous_only=params.ambiguous_only,
        scheduled_from=params.scheduled_from,
        scheduled_to=params.scheduled_to,
        published_from=params.published_from,
        published_to=params.published_to,
        min_attempts=params.min_attempts,
        max_attempts=params.max_attempts,
    )
