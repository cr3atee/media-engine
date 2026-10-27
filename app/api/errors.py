from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import structlog
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.services.admin_mutations import AdminCommandError

logger = structlog.get_logger(__name__)


class ApiError(Exception):
    """Safe, stable application error intended for an HTTP response."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = dict(details or {})
        super().__init__(message)


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render one application error without exposing internal details."""
    error = cast(ApiError, exc)
    return _response(
        request,
        status_code=error.status_code,
        code=error.code,
        message=error.message,
        details=error.details,
    )


async def admin_command_error_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Map stable application command failures to sanitized HTTP conflicts."""
    error = cast(AdminCommandError, exc)
    status_code = 404 if error.code == "resource_not_found" else 409
    return _response(
        request,
        status_code=status_code,
        code=error.code,
        message=error.message,
        details=error.details,
    )


async def validation_error_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Render validation failures using the common public envelope."""
    validation_error = cast(RequestValidationError, exc)
    details = {
        "fields": [
            {
                "field": ".".join(str(part) for part in error["loc"]),
                "message": str(error["msg"]),
                "type": str(error["type"]),
            }
            for error in validation_error.errors()
        ]
    }
    return _response(
        request,
        status_code=422,
        code="validation_error",
        message="Request validation failed.",
        details=details,
    )


async def http_error_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Normalize framework HTTP errors into the public envelope."""
    http_error = cast(StarletteHTTPException, exc)
    status = http_error.status_code
    if status == 404:
        code = "not_found"
        message = "Resource was not found."
    elif status == 405:
        code = "method_not_allowed"
        message = "HTTP method is not allowed."
    else:
        code = "http_error"
        message = "The request could not be completed."
    return _response(
        request,
        status_code=status,
        code=code,
        message=message,
        details={},
    )


async def unexpected_error_handler(
    request: Request,
    exc: Exception,
) -> Response:
    """Persist sanitized diagnostics and return a credential-free response."""
    from app.services.diagnostics import DiagnosticService

    service = getattr(request.app.state, "diagnostic_service", None)
    incident = None
    if isinstance(service, DiagnosticService):
        route = getattr(request.scope.get("route"), "path", "__unmatched__")
        incident = await service.record_backend(
            request_id=get_request_id(request),
            route=route,
            method=request.method,
            error=exc,
        )
    logger.error(
        "api_internal_error",
        request_id=get_request_id(request),
        exception_type=type(exc).__name__,
        incident_id=str(incident.id) if incident is not None else "unavailable",
    )
    if request.url.path.startswith("/terminal"):
        from app.api.routes.terminal import terminal_error_response

        return terminal_error_response(
            request_id=get_request_id(request),
            incident_id=str(incident.id) if incident is not None else "unavailable",
        )
    return _response(
        request,
        status_code=500,
        code="internal_error",
        message="An internal error occurred.",
        details={
            "incident_id": str(incident.id) if incident is not None else "unavailable"
        },
    )


def get_request_id(request: Request) -> str:
    """Return the correlation ID installed by request middleware."""
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) and value else "unavailable"


def _response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: Mapping[str, Any],
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": dict(details),
                "request_id": get_request_id(request),
            }
        },
    )
