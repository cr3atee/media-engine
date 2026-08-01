from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Annotated

from fastapi import Request, Security
from fastapi.security import APIKeyHeader

from app.api.errors import ApiError
from app.config.settings import AdminApiSettings

ADMIN_API_KEY_HEADER = "X-Admin-API-Key"
_admin_api_key = APIKeyHeader(
    name=ADMIN_API_KEY_HEADER,
    scheme_name="AdminApiKey",
    description="Environment-provided administration API key.",
    auto_error=False,
)


@dataclass(slots=True, frozen=True)
class AdminPrincipal:
    """Minimal authenticated principal for the initial administration API."""

    actor_id: str
    role: str


async def require_admin(
    request: Request,
    api_key: Annotated[str | None, Security(_admin_api_key)] = None,
) -> AdminPrincipal:
    """Require the configured admin key using constant-time comparison."""
    configuration = get_admin_settings(request)
    if configuration.test_bypass_enabled and getattr(
        request.app.state, "admin_api_test_mode", False
    ):
        return AdminPrincipal(actor_id="test-admin", role="administrator")

    configured_key = configuration.api_key.get_secret_value()
    if (
        not configuration.api_enabled
        or not configured_key
        or api_key is None
        or not hmac.compare_digest(api_key, configured_key)
    ):
        raise ApiError(
            401,
            "authentication_required",
            "Valid administration authentication is required.",
        )
    return AdminPrincipal(actor_id="configured-admin", role="administrator")


def get_admin_settings(request: Request) -> AdminApiSettings:
    """Return request-scoped API settings, allowing explicit test composition."""
    value = getattr(request.app.state, "admin_api_settings", None)
    if isinstance(value, AdminApiSettings):
        return value
    from app.config.settings import settings

    return settings.admin_api
