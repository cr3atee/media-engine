from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.auth import AdminPrincipal, require_admin
from app.api.dependencies import get_event_query_service
from app.api.errors import ApiError
from app.api.mappers import event_response
from app.api.routes.helpers import enum_value, next_cursor, page_request
from app.api.schemas.common import PageResponse
from app.api.schemas.events import EventQueryParams, EventResponse
from app.repositories.queries.models import EventQuery
from app.services.admin_queries import AdminEventQueryService

router = APIRouter(prefix="/api/v1/admin/events", tags=["Events"])


@router.get("", response_model=PageResponse[EventResponse])
async def list_events(
    request: Request,
    params: Annotated[EventQueryParams, Depends()],
    _principal: Annotated[AdminPrincipal, Depends(require_admin)],
    service: Annotated[
        AdminEventQueryService,
        Depends(get_event_query_service),
    ],
) -> PageResponse[EventResponse]:
    """List durable market events without changing lifecycle state."""
    page = page_request(request, resource="events", params=params)
    result = await service.list_events(
        EventQuery(
            marketplace=params.marketplace,
            event_type=enum_value(params.event_type),
            disposition=enum_value(params.disposition),
            scoring_status=enum_value(params.scoring_status),
            content_generation_status=enum_value(params.content_generation_status),
            review_status=enum_value(params.review_status),
            publication_status=enum_value(params.publication_status),
            min_score=params.min_score,
            external_id=params.external_id,
            search=params.search,
            canonical_product_id=params.canonical_product_id,
            created_from=params.created_from,
            created_to=params.created_to,
            detected_from=params.detected_from,
            detected_to=params.detected_to,
            has_content=params.has_content,
            has_publication=params.has_publication,
            has_failure=params.has_failure,
            ambiguous_only=params.ambiguous_only,
        ),
        page,
    )
    return PageResponse(
        items=[event_response(item) for item in result.items],
        next_cursor=next_cursor(request, position=result.next_cursor),
        page_size=page.limit,
    )


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    request: Request,
    event_id: UUID,
    _principal: Annotated[AdminPrincipal, Depends(require_admin)],
    service: Annotated[
        AdminEventQueryService,
        Depends(get_event_query_service),
    ],
) -> EventResponse:
    """Return one durable market event."""
    event = await service.get_event(event_id)
    if event is None:
        raise ApiError(404, "not_found", "Market event was not found.")
    return event_response(event)
