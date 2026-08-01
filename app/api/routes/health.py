from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal, cast

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

from app.api.auth import get_admin_settings, require_admin
from app.api.schemas.health import HealthComponent, HealthResponse
from app.config.settings import AdminApiSettings, settings
from app.database.session import engine

router = APIRouter(tags=["Health"])
_ALEMBIC_CONFIG_PATH = Path(__file__).resolve().parents[3] / "alembic.ini"


@router.get("/health/live", response_model=HealthResponse)
async def liveness(request: Request) -> HealthResponse:
    """Report process liveness without touching external infrastructure."""
    return HealthResponse(
        status="ok",
        service="mediaengine",
        database="not_checked",
        admin_api=_admin_status(_settings_for(request)),
        migration="not_checked",
        repositories="not_checked",
        scheduler=_scheduler_status(request),
        telegram=_telegram_status(),
        components={
            "database": HealthComponent(status="not_checked", required=True),
            "migration": HealthComponent(status="not_checked", required=True),
            "repositories": HealthComponent(status="not_checked", required=True),
            "scheduler": HealthComponent(
                status=_scheduler_status(request),
                required=False,
            ),
            "telegram": HealthComponent(status=_telegram_status(), required=False),
        },
    )


@router.get("/health/ready", response_model=HealthResponse)
async def readiness(request: Request) -> HealthResponse:
    """Report sanitized database/application readiness."""
    probe = getattr(request.app.state, "readiness_probe", None)
    migration_status: Literal["not_checked", "head", "behind", "unavailable"] = (
        "not_checked"
    )
    try:
        if probe is None:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
                current_revision = await connection.run_sync(_current_revision)
            migration_status = _migration_status(current_revision)
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
            migration="unavailable",
            repositories=_repository_status(request),
            scheduler=_scheduler_status(request),
            telegram=_telegram_status(),
            components={
                "database": HealthComponent(status="unavailable", required=True),
                "migration": HealthComponent(status="unavailable", required=True),
                "repositories": HealthComponent(
                    status=_repository_status(request),
                    required=True,
                ),
                "scheduler": HealthComponent(
                    status=_scheduler_status(request),
                    required=False,
                ),
                "telegram": HealthComponent(
                    status=_telegram_status(),
                    required=False,
                ),
            },
        )
    admin_api = _admin_status(_settings_for(request))
    repository_status = _repository_status(request)
    service_status: Literal["ok", "not_ready"] = (
        "ok"
        if (
            migration_status in {"head", "not_checked"}
            and admin_api == "configured"
            and repository_status == "configured"
        )
        else "not_ready"
    )
    return HealthResponse(
        status=service_status,
        service="mediaengine",
        database="ok",
        admin_api=admin_api,
        migration=migration_status,
        repositories=repository_status,
        scheduler=_scheduler_status(request),
        telegram=_telegram_status(),
        components={
            "database": HealthComponent(status="ok", required=True),
            "migration": HealthComponent(
                status=migration_status,
                required=True,
            ),
            "repositories": HealthComponent(
                status=repository_status,
                required=True,
            ),
            "scheduler": HealthComponent(
                status=_scheduler_status(request),
                required=False,
            ),
            "telegram": HealthComponent(status=_telegram_status(), required=False),
        },
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


def _repository_status(
    request: Request,
) -> Literal["configured", "not_configured"]:
    if (
        getattr(request.app.state, "read_repository_scope_factory", None) is None
        or getattr(request.app.state, "repository_scope_factory", None) is None
    ):
        return "not_configured"
    return "configured"


def _scheduler_status(request: Request) -> Literal["configured", "not_configured"]:
    if getattr(request.app.state, "scheduler", None) is None:
        return "not_configured"
    return "configured"


def _telegram_status() -> Literal["disabled", "dry_run", "configured", "live_enabled"]:
    telegram = settings.telegram
    if not telegram.delivery_enabled:
        return "disabled"
    if telegram.dry_run:
        return "dry_run"
    if telegram.allow_live_delivery:
        return "live_enabled"
    return "configured"


def _current_revision(connection: Any) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


def _migration_status(
    current_revision: str | None,
) -> Literal["head", "behind"]:
    script = ScriptDirectory.from_config(Config(str(_ALEMBIC_CONFIG_PATH)))
    head_revision = script.get_current_head()
    return "head" if current_revision == head_revision else "behind"
