from __future__ import annotations

from typing import Literal

from app.api.schemas.common import ApiModel


class HealthResponse(ApiModel):
    """Sanitized liveness or readiness response."""

    status: Literal["ok", "not_ready"]
    service: str
    database: Literal["not_checked", "ok", "unavailable"]
    admin_api: Literal["configured", "not_configured", "disabled"]
