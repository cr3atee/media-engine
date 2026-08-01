from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.auth import AdminPrincipal, require_admin
from app.api.dependencies import get_dashboard_query_service
from app.api.errors import ApiError
from app.api.mappers import dashboard_summary_response
from app.api.schemas.dashboard import DashboardQueryParams, DashboardSummaryResponse
from app.services.admin_queries import AdminDashboardQueryService

router = APIRouter(prefix="/api/v1/admin/dashboard", tags=["Dashboard"])


@router.get("/summary", response_model=DashboardSummaryResponse)
async def dashboard_summary(
    request: Request,
    params: Annotated[DashboardQueryParams, Depends(_dashboard_query_params)],
    _principal: Annotated[AdminPrincipal, Depends(require_admin)],
    service: Annotated[
        AdminDashboardQueryService,
        Depends(get_dashboard_query_service),
    ],
) -> DashboardSummaryResponse:
    """Return bounded operational counters for a UTC time window."""
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
    summary = await service.get_summary(window)
    return dashboard_summary_response(summary)


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
