from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.auth import AdminPrincipal, require_admin
from app.api.dependencies import get_content_query_service
from app.api.errors import ApiError
from app.api.mappers import content_response
from app.api.routes.helpers import enum_value, next_cursor, page_request
from app.api.schemas.common import PageResponse
from app.api.schemas.content import ContentQueryParams, ContentResponse
from app.repositories.queries.models import ContentQuery
from app.services.admin_queries import AdminContentQueryService

router = APIRouter(prefix="/api/v1/admin/content", tags=["Content"])
event_content_router = APIRouter(
    prefix="/api/v1/admin/events",
    tags=["Content"],
)


@router.get("", response_model=PageResponse[ContentResponse])
async def list_content(
    request: Request,
    params: Annotated[ContentQueryParams, Depends()],
    _principal: Annotated[AdminPrincipal, Depends(require_admin)],
    service: Annotated[
        AdminContentQueryService,
        Depends(get_content_query_service),
    ],
) -> PageResponse[ContentResponse]:
    """List generated-content attempts without changing review state."""
    page = page_request(request, resource="content", params=params)
    result = await service.list_content(_content_query(params), page)
    return PageResponse(
        items=[content_response(item) for item in result.items],
        next_cursor=next_cursor(request, position=result.next_cursor),
        page_size=page.limit,
    )


@router.get("/{content_id}", response_model=ContentResponse)
async def get_content(
    content_id: UUID,
    _principal: Annotated[AdminPrincipal, Depends(require_admin)],
    service: Annotated[
        AdminContentQueryService,
        Depends(get_content_query_service),
    ],
) -> ContentResponse:
    """Return one generated-content attempt as plain data."""
    content = await service.get_content(content_id)
    if content is None:
        raise ApiError(404, "not_found", "Generated content was not found.")
    return content_response(content)


@event_content_router.get(
    "/{event_id}/content",
    response_model=PageResponse[ContentResponse],
)
async def list_event_content(
    request: Request,
    event_id: UUID,
    params: Annotated[ContentQueryParams, Depends()],
    _principal: Annotated[AdminPrincipal, Depends(require_admin)],
    service: Annotated[
        AdminContentQueryService,
        Depends(get_content_query_service),
    ],
) -> PageResponse[ContentResponse]:
    """List content attempts related to one event."""
    scoped = params.model_copy(update={"event_id": event_id})
    page = page_request(request, resource="content", params=scoped)
    result = await service.list_content(_content_query(scoped), page)
    return PageResponse(
        items=[content_response(item) for item in result.items],
        next_cursor=next_cursor(request, position=result.next_cursor),
        page_size=page.limit,
    )


def _content_query(params: ContentQueryParams) -> ContentQuery:
    return ContentQuery(
        event_id=params.event_id,
        search=params.search,
        generation_status=enum_value(params.generation_status),
        review_status=enum_value(params.review_status),
        attempt_number=params.attempt_number,
        created_from=params.created_from,
        created_to=params.created_to,
        completed_from=params.completed_from,
        completed_to=params.completed_to,
        has_publication=params.has_publication,
        failed_only=params.failed_only,
    )
