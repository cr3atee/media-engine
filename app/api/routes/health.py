from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal, cast

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

from app.api.auth import get_admin_settings, require_admin
from app.api.schemas.health import HealthResponse
from app.config.settings import AdminApiSettings
from app.database.session import engine

router = APIRouter(tags=["Health"])


@router.get("/health/live", response_model=HealthResponse)
async def liveness(request: Request) -> HealthResponse:
    """Report process liveness without touching external infrastructure."""
    return HealthResponse(
        status="ok",
        service="mediaengine",
        database="not_checked",
        admin_api=_admin_status(_settings_for(request)),
    )


@router.get("/health/ready", response_model=HealthResponse)
async def readiness(request: Request) -> HealthResponse:
    """Report sanitized database/application readiness."""
    probe = getattr(request.app.state, "readiness_probe", None)
    try:
        if probe is None:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        else:
            result = cast(Callable[[], Awaitable[bool]], probe)
            if not await result():
                raise RuntimeError("readiness probe reported unavailable")
    except Exception:
        return HealthResponse(
            status="not_ready",
            service="mediaengine",
            database="unavailable",
            admin_api=_admin_status(_settings_for(request)),
        )
    return HealthResponse(
        status="ok",
        service="mediaengine",
        database="ok",
        admin_api=_admin_status(_settings_for(request)),
    )


@router.get(
    "/api/v1/admin/health",
    response_model=HealthResponse,
    dependencies=[Depends(require_admin)],
)
async def admin_health(request: Request) -> HealthResponse:
    """Return authenticated administration health information."""
    return await liveness(request)


@router.get(
    "/api/v1/admin/readiness",
    response_model=HealthResponse,
    dependencies=[Depends(require_admin)],
)
async def admin_readiness(request: Request) -> HealthResponse:
    """Return authenticated administration readiness information."""
    return await readiness(request)


def _settings_for(request: Request) -> AdminApiSettings:
    return get_admin_settings(request)


def _admin_status(
    configuration: AdminApiSettings,
) -> Literal["configured", "not_configured", "disabled"]:
    if not configuration.api_enabled:
        return "disabled"
    if not configuration.api_key.get_secret_value():
        return "not_configured"
    return "configured"
