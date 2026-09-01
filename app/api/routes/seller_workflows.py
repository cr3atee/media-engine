from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import (
    get_admin_mutation_service,
    get_content_query_service,
    get_dashboard_query_service,
    get_event_query_service,
    get_publication_query_service,
    require_idempotency_key,
    require_tenant_permission,
)
from app.api.errors import ApiError, get_request_id
from app.api.mappers import (
    content_response,
    dashboard_summary_response,
    event_response,
    publication_response,
)
from app.api.routes.helpers import enum_value, next_cursor, page_request
from app.api.schemas.admin_mutations import (
    AdminMutationResponse,
    ApproveContentRequest,
    PublicationCancelRequest,
    PublicationRetryRequest,
    RejectContentRequest,
    ResolveAmbiguousPublicationRequest,
)
from app.api.schemas.common import PageResponse
from app.api.schemas.content import ContentQueryParams, ContentResponse
from app.api.schemas.dashboard import DashboardQueryParams, DashboardSummaryResponse
from app.api.schemas.events import EventQueryParams, EventResponse
from app.api.schemas.publications import PublicationQueryParams, PublicationResponse
from app.domain.admin_actions import AdminActorType
from app.domain.auth import Permission, TenantContext
from app.repositories.queries.models import (
    ContentQuery,
    DashboardWindow,
    EventQuery,
    PublicationQuery,
)
from app.services.admin_mutations import (
    AdminCommandContext,
    AdminMutationResult,
    AdminMutationService,
    ContentReviewCommand,
    PublicationCommand,
    ResolvePublicationCommand,
)
from app.services.admin_queries import (
    AdminContentQueryService,
    AdminDashboardQueryService,
    AdminEventQueryService,
    AdminPublicationQueryService,
)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}",
    tags=["Seller tenant workflows"],
)

EventsTenant = Annotated[
    TenantContext,
    Depends(require_tenant_permission(Permission.EVENTS_READ)),
]
ContentTenant = Annotated[
    TenantContext,
    Depends(require_tenant_permission(Permission.CONTENT_READ)),
]
PublicationsTenant = Annotated[
    TenantContext,
    Depends(require_tenant_permission(Permission.PUBLICATIONS_READ)),
]
DashboardTenant = Annotated[
    TenantContext,
    Depends(require_tenant_permission(Permission.DASHBOARD_READ)),
]
ContentReviewTenant = Annotated[
    TenantContext,
    Depends(require_tenant_permission(Permission.CONTENT_REVIEW)),
]
PublicationOperateTenant = Annotated[
    TenantContext,
    Depends(require_tenant_permission(Permission.PUBLICATION_OPERATE)),
]


@router.get("/events", response_model=PageResponse[EventResponse])
async def list_tenant_events(
    request: Request,
    params: Annotated[EventQueryParams, Depends()],
    context: EventsTenant,
    service: Annotated[AdminEventQueryService, Depends(get_event_query_service)],
) -> PageResponse[EventResponse]:
    """List tenant-owned durable market events."""
    page = page_request(
        request,
        resource="tenant_events",
        params=params,
        extra_filters={"tenant_id": str(context.tenant.id)},
    )
    result = await service.list_events(
        EventQuery(
            tenant_id=context.tenant.id,
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


@router.get("/events/{event_id}", response_model=EventResponse)
async def get_tenant_event(
    event_id: UUID,
    context: EventsTenant,
    service: Annotated[AdminEventQueryService, Depends(get_event_query_service)],
) -> EventResponse:
    """Return one tenant-owned durable market event."""
    event = await service.get_event(event_id, context.tenant.id)
    if event is None:
        raise ApiError(404, "not_found", "Market event was not found.")
    return event_response(event)


@router.get("/content", response_model=PageResponse[ContentResponse])
async def list_tenant_content(
    request: Request,
    params: Annotated[ContentQueryParams, Depends()],
    context: ContentTenant,
    service: Annotated[
        AdminContentQueryService,
        Depends(get_content_query_service),
    ],
) -> PageResponse[ContentResponse]:
    """List tenant-owned generated-content attempts."""
    page = page_request(
        request,
        resource="tenant_content",
        params=params,
        extra_filters={"tenant_id": str(context.tenant.id)},
    )
    result = await service.list_content(_content_query(params, context.tenant.id), page)
    return PageResponse(
        items=[content_response(item) for item in result.items],
        next_cursor=next_cursor(request, position=result.next_cursor),
        page_size=page.limit,
    )


@router.get("/content/{content_id}", response_model=ContentResponse)
async def get_tenant_content(
    content_id: UUID,
    context: ContentTenant,
    service: Annotated[
        AdminContentQueryService,
        Depends(get_content_query_service),
    ],
) -> ContentResponse:
    """Return one tenant-owned generated-content attempt."""
    content = await service.get_content(content_id, context.tenant.id)
    if content is None:
        raise ApiError(404, "not_found", "Generated content was not found.")
    return content_response(content)


@router.get(
    "/events/{event_id}/content",
    response_model=PageResponse[ContentResponse],
)
async def list_tenant_event_content(
    request: Request,
    event_id: UUID,
    params: Annotated[ContentQueryParams, Depends()],
    context: ContentTenant,
    service: Annotated[
        AdminContentQueryService,
        Depends(get_content_query_service),
    ],
) -> PageResponse[ContentResponse]:
    """List tenant-owned content attempts for one event."""
    scoped = params.model_copy(update={"event_id": event_id})
    page = page_request(
        request,
        resource="tenant_content",
        params=scoped,
        extra_filters={"tenant_id": str(context.tenant.id)},
    )
    result = await service.list_content(_content_query(scoped, context.tenant.id), page)
    return PageResponse(
        items=[content_response(item) for item in result.items],
        next_cursor=next_cursor(request, position=result.next_cursor),
        page_size=page.limit,
    )


@router.get("/publications", response_model=PageResponse[PublicationResponse])
async def list_tenant_publications(
    request: Request,
    params: Annotated[PublicationQueryParams, Depends()],
    context: PublicationsTenant,
    service: Annotated[
        AdminPublicationQueryService,
        Depends(get_publication_query_service),
    ],
) -> PageResponse[PublicationResponse]:
    """List tenant-owned publication intents."""
    page = page_request(
        request,
        resource="tenant_publications",
        params=params,
        extra_filters={"tenant_id": str(context.tenant.id)},
    )
    result = await service.list_publications(
        _publication_query(params, context.tenant.id),
        page,
    )
    return PageResponse(
        items=[publication_response(item) for item in result.items],
        next_cursor=next_cursor(request, position=result.next_cursor),
        page_size=page.limit,
    )


@router.get("/publications/{publication_id}", response_model=PublicationResponse)
async def get_tenant_publication(
    publication_id: UUID,
    context: PublicationsTenant,
    service: Annotated[
        AdminPublicationQueryService,
        Depends(get_publication_query_service),
    ],
) -> PublicationResponse:
    """Return one tenant-owned publication intent."""
    publication = await service.get_publication(publication_id, context.tenant.id)
    if publication is None:
        raise ApiError(404, "not_found", "Publication was not found.")
    return publication_response(publication)


@router.get(
    "/events/{event_id}/publications",
    response_model=PageResponse[PublicationResponse],
)
async def list_tenant_event_publications(
    request: Request,
    event_id: UUID,
    params: Annotated[PublicationQueryParams, Depends()],
    context: PublicationsTenant,
    service: Annotated[
        AdminPublicationQueryService,
        Depends(get_publication_query_service),
    ],
) -> PageResponse[PublicationResponse]:
    """List tenant-owned publication intents for one event."""
    scoped = params.model_copy(update={"event_id": event_id})
    page = page_request(
        request,
        resource="tenant_publications",
        params=scoped,
        extra_filters={"tenant_id": str(context.tenant.id)},
    )
    result = await service.list_publications(
        _publication_query(scoped, context.tenant.id),
        page,
    )
    return PageResponse(
        items=[publication_response(item) for item in result.items],
        next_cursor=next_cursor(request, position=result.next_cursor),
        page_size=page.limit,
    )


@router.get("/dashboard/summary", response_model=DashboardSummaryResponse)
async def tenant_dashboard_summary(
    request: Request,
    params: Annotated[DashboardQueryParams, Depends(_dashboard_query_params)],
    context: DashboardTenant,
    service: Annotated[
        AdminDashboardQueryService,
        Depends(get_dashboard_query_service),
    ],
) -> DashboardSummaryResponse:
    """Return tenant-scoped operational counters for a UTC time window."""
    clock = getattr(request.app.state, "dashboard_clock", None)
    now = clock() if callable(clock) else None
    try:
        window = params.window(now=now)
    except ValueError as exc:
        raise ApiError(
            422,
            "invalid_dashboard_window",
            "Dashboard time window is invalid.",
        ) from exc
    summary = await service.get_summary(
        DashboardWindow(
            starts_at=window.starts_at,
            ends_at=window.ends_at,
            tenant_id=context.tenant.id,
        )
    )
    return dashboard_summary_response(summary)


@router.post(
    "/content/{content_id}/approve",
    response_model=AdminMutationResponse,
)
async def approve_tenant_content(
    request: Request,
    content_id: UUID,
    payload: ApproveContentRequest,
    context: ContentReviewTenant,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    service: Annotated[AdminMutationService, Depends(get_admin_mutation_service)],
) -> AdminMutationResponse:
    """Approve tenant-owned generated content through the command service."""
    result = await service.approve(
        ContentReviewCommand(
            content_id=content_id,
            expected_version=payload.expected_version,
            reason=payload.reason,
        ),
        _command_context(request, context, idempotency_key),
    )
    return _response(result)


@router.post(
    "/content/{content_id}/reject",
    response_model=AdminMutationResponse,
)
async def reject_tenant_content(
    request: Request,
    content_id: UUID,
    payload: RejectContentRequest,
    context: ContentReviewTenant,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    service: Annotated[AdminMutationService, Depends(get_admin_mutation_service)],
) -> AdminMutationResponse:
    """Reject tenant-owned generated content through the command service."""
    result = await service.reject(
        ContentReviewCommand(
            content_id=content_id,
            expected_version=payload.expected_version,
            reason=payload.reason,
        ),
        _command_context(request, context, idempotency_key),
    )
    return _response(result)


@router.post(
    "/publications/{publication_id}/retry",
    response_model=AdminMutationResponse,
)
async def retry_tenant_publication(
    request: Request,
    publication_id: UUID,
    payload: PublicationRetryRequest,
    context: PublicationOperateTenant,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    service: Annotated[AdminMutationService, Depends(get_admin_mutation_service)],
) -> AdminMutationResponse:
    """Retry one tenant-owned publication without contacting its provider."""
    result = await service.retry(
        PublicationCommand(
            publication_id=publication_id,
            expected_version=payload.expected_version,
            reason=payload.reason,
        ),
        _command_context(request, context, idempotency_key),
    )
    return _response(result)


@router.post(
    "/publications/{publication_id}/cancel",
    response_model=AdminMutationResponse,
)
async def cancel_tenant_publication(
    request: Request,
    publication_id: UUID,
    payload: PublicationCancelRequest,
    context: PublicationOperateTenant,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    service: Annotated[AdminMutationService, Depends(get_admin_mutation_service)],
) -> AdminMutationResponse:
    """Cancel tenant-owned pending or retryable publication work."""
    result = await service.cancel(
        PublicationCommand(
            publication_id=publication_id,
            expected_version=payload.expected_version,
            reason=payload.reason,
        ),
        _command_context(request, context, idempotency_key),
    )
    return _response(result)


@router.post(
    "/publications/{publication_id}/resolve-ambiguous",
    response_model=AdminMutationResponse,
)
async def resolve_tenant_ambiguous_publication(
    request: Request,
    publication_id: UUID,
    payload: ResolveAmbiguousPublicationRequest,
    context: PublicationOperateTenant,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    service: Annotated[AdminMutationService, Depends(get_admin_mutation_service)],
) -> AdminMutationResponse:
    """Resolve one tenant-owned ambiguous delivery outcome."""
    result = await service.resolve_ambiguous(
        ResolvePublicationCommand(
            publication_id=publication_id,
            expected_version=payload.expected_version,
            resolution=payload.resolution,
            reason=payload.reason,
            external_message_id=payload.external_message_id,
        ),
        _command_context(request, context, idempotency_key),
    )
    return _response(result)


async def _dashboard_query_params(
    from_: Annotated[
        datetime | None,
        Query(alias="from", description="Inclusive UTC window start."),
    ] = None,
    to: Annotated[
        datetime | None,
        Query(description="Exclusive UTC window end."),
    ] = None,
) -> DashboardQueryParams:
    """Build dashboard query params while preserving the public `from` name."""
    return DashboardQueryParams.model_validate({"from": from_, "to": to})


def _content_query(params: ContentQueryParams, tenant_id: UUID) -> ContentQuery:
    return ContentQuery(
        tenant_id=tenant_id,
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


def _publication_query(
    params: PublicationQueryParams,
    tenant_id: UUID,
) -> PublicationQuery:
    return PublicationQuery(
        tenant_id=tenant_id,
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


def _command_context(
    request: Request,
    context: TenantContext,
    idempotency_key: str,
) -> AdminCommandContext:
    return AdminCommandContext(
        actor_id=str(context.principal.user_id),
        request_id=get_request_id(request),
        idempotency_key=idempotency_key,
        tenant_id=context.tenant.id,
        actor_type=AdminActorType.USER,
        elevated=False,
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
