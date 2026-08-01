from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.api.schemas.common import ApiModel


class HealthComponent(ApiModel):
    """Sanitized status for one infrastructure component."""

    status: Literal[
        "ok",
        "not_checked",
        "unavailable",
        "head",
        "behind",
        "configured",
        "not_configured",
        "disabled",
        "dry_run",
        "live_enabled",
    ]
    required: bool
    detail: str | None = None


class HealthResponse(ApiModel):
    """Sanitized liveness or readiness response."""

    status: Literal["ok", "not_ready"]
    service: str
    database: Literal["not_checked", "ok", "unavailable"]
    admin_api: Literal["configured", "not_configured", "disabled"]
    migration: Literal["not_checked", "head", "behind", "unavailable"] = "not_checked"
    repositories: Literal["not_checked", "configured", "not_configured"] = "not_checked"
    scheduler: Literal["not_checked", "configured", "not_configured"] = "not_checked"
    telegram: Literal["disabled", "dry_run", "configured", "live_enabled"] = "disabled"
    components: dict[str, HealthComponent] = Field(default_factory=dict)
