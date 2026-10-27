"""Frontend diagnostic intake and product-admin incident journal routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.dependencies import get_diagnostic_service, require_seller_principal
from app.api.errors import ApiError, get_request_id
from app.api.schemas.diagnostics import (
    DiagnosticAcceptedResponse,
    DiagnosticIncidentPageResponse,
    DiagnosticIncidentResponse,
    FrontendDiagnosticRequest,
)
from app.domain.auth import AuthenticatedPrincipal
from app.domain.diagnostics import DiagnosticSeverity, DiagnosticSource
from app.services.diagnostics import DiagnosticAccessError, DiagnosticService

router = APIRouter(prefix="/api/v1", tags=["diagnostics"])


@router.post(
    "/diagnostics/frontend",
    response_model=DiagnosticAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def report_frontend_diagnostic(
    report: FrontendDiagnosticRequest,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_seller_principal)],
    service: Annotated[DiagnosticService, Depends(get_diagnostic_service)],
) -> DiagnosticAcceptedResponse:
    """Accept bounded metadata from an authenticated browser session."""
    try:
        incident = await service.record_frontend(
            principal,
            kind=report.kind,
            page=report.page,
            component=report.component,
            action=report.action,
            request_id=(
                report.request_id
                if report.request_id != "unavailable"
                else get_request_id(request)
            ),
        )
    except DiagnosticAccessError as exc:
        raise _api_error(exc) from exc
    return DiagnosticAcceptedResponse(incident_id=incident.id)


@router.get(
    "/platform/diagnostics",
    response_model=DiagnosticIncidentPageResponse,
)
async def list_diagnostic_incidents(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_seller_principal)],
    service: Annotated[DiagnosticService, Depends(get_diagnostic_service)],
    source: Annotated[DiagnosticSource | None, Query()] = None,
    severity: Annotated[DiagnosticSeverity | None, Query()] = None,
    component: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    environment: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DiagnosticIncidentPageResponse:
    """List sanitized incidents after a live product-admin role check."""
    try:
        incidents, total = await service.list_for_admin(
            principal,
            source=source,
            severity=severity,
            component=component,
            environment=environment,
            limit=limit,
            offset=offset,
        )
    except DiagnosticAccessError as exc:
        raise _api_error(exc) from exc
    return DiagnosticIncidentPageResponse(
        items=[DiagnosticIncidentResponse.model_validate(item) for item in incidents],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/platform/diagnostics/{incident_id}",
    response_model=DiagnosticIncidentResponse,
)
async def get_diagnostic_incident(
    incident_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_seller_principal)],
    service: Annotated[DiagnosticService, Depends(get_diagnostic_service)],
) -> DiagnosticIncidentResponse:
    """Return one sanitized incident to a current product administrator."""
    try:
        incident = await service.get_for_admin(principal, incident_id)
    except DiagnosticAccessError as exc:
        raise _api_error(exc) from exc
    return DiagnosticIncidentResponse.model_validate(incident)


def _api_error(error: DiagnosticAccessError) -> ApiError:
    messages = {
        "product_admin_required": "Product administrator permission is required.",
        "diagnostic_not_found": "Diagnostic incident was not found.",
        "diagnostic_rate_limited": "Diagnostic report rate limit was exceeded.",
    }
    return ApiError(
        error.status_code,
        error.code,
        messages.get(error.code, "Diagnostic request could not be completed."),
    )
