from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from app.core.http_client import HttpClient
from app.domain.marketplace_integrations import (
    MarketplaceAuthType,
    MarketplaceCredentialMetadata,
    MarketplaceIntegration,
)
from app.services.marketplace_credentials import (
    EnvironmentMarketplaceCredentialResolver,
    MarketplaceCredentialResolutionError,
)
from app.services.playerok_connector import (
    PlayerokConnector,
    PlayerokConnectorConfigurationError,
)

TENANT_ID = UUID("10000000-0000-4000-8000-000000000901")
INTEGRATION_ID = UUID("20000000-0000-4000-8000-000000000901")
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run one async connector check without an external plugin."""
    return asyncio.run(awaitable)


def make_integration(
    *,
    auth_type: MarketplaceAuthType,
    credential: MarketplaceCredentialMetadata | None,
) -> MarketplaceIntegration:
    """Create one Playerok integration with explicit auth metadata."""
    return MarketplaceIntegration(
        id=INTEGRATION_ID,
        tenant_id=TENANT_ID,
        marketplace="playerok",
        display_name="Playerok session",
        source_url="https://playerok.com/graphql",
        auth_type=auth_type,
        credential=credential,
        created_at=NOW,
        updated_at=NOW,
    )


def credential_metadata() -> MarketplaceCredentialMetadata:
    """Create one opaque credential reference."""
    return MarketplaceCredentialMetadata(
        reference="env://PLAYEROK_MAIN",
        configured_at=NOW,
    )


def test_environment_resolver_scopes_variables_by_tenant_and_integration() -> None:
    variable = (
        "MEDIAENGINE_MARKETPLACE_SECRET_"
        f"{TENANT_ID.hex.upper()}_{INTEGRATION_ID.hex.upper()}_PLAYEROK_MAIN"
    )
    resolver = EnvironmentMarketplaceCredentialResolver({variable: "private-value"})

    secret = run_async(
        resolver.resolve(
            tenant_id=TENANT_ID,
            integration_id=INTEGRATION_ID,
            reference="env://PLAYEROK_MAIN",
        )
    )

    assert secret.get_secret_value() == "private-value"
    with pytest.raises(MarketplaceCredentialResolutionError) as error:
        run_async(
            resolver.resolve(
                tenant_id=UUID(int=1),
                integration_id=INTEGRATION_ID,
                reference="env://PLAYEROK_MAIN",
            )
        )
    assert "PLAYEROK_MAIN" not in str(error.value)


def test_connector_resolves_session_for_exact_integration() -> None:
    client = _RecordingHttpClient()
    resolver = _RecordingResolver()
    connector = PlayerokConnector(
        http_client=cast(HttpClient, client),
        integration=make_integration(
            auth_type=MarketplaceAuthType.SESSION,
            credential=credential_metadata(),
        ),
        credential_resolver=resolver,
    )

    offers = run_async(connector.run("https://playerok.com/graphql"))

    assert len(offers) == 1
    assert offers[0].external_id == "offer-1"
    assert resolver.calls == [(TENANT_ID, INTEGRATION_ID, "env://PLAYEROK_MAIN")]
    assert "Cookie" in client.headers


def test_public_connector_does_not_require_or_send_credentials() -> None:
    client = _RecordingHttpClient()
    connector = PlayerokConnector(
        http_client=cast(HttpClient, client),
        integration=make_integration(
            auth_type=MarketplaceAuthType.NONE,
            credential=None,
        ),
        credential_resolver=None,
    )

    offers = run_async(connector.run("https://playerok.com/graphql"))

    assert len(offers) == 1
    assert "Cookie" not in client.headers


def test_authenticated_connector_fails_closed_without_resolver() -> None:
    connector = PlayerokConnector(
        http_client=cast(HttpClient, _RecordingHttpClient()),
        integration=make_integration(
            auth_type=MarketplaceAuthType.COOKIE,
            credential=credential_metadata(),
        ),
        credential_resolver=None,
    )

    with pytest.raises(
        PlayerokConnectorConfigurationError,
        match="resolver is unavailable",
    ):
        run_async(connector.run("https://playerok.com/graphql"))


class _RecordingResolver:
    """Return one secret while recording the tenant-scoped lookup."""

    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID, str]] = []

    async def resolve(
        self,
        *,
        tenant_id: UUID,
        integration_id: UUID,
        reference: str,
    ) -> SecretStr:
        self.calls.append((tenant_id, integration_id, reference))
        return SecretStr(
            json.dumps(
                {
                    "user_agent": "Playerok connector browser/1.0",
                    "cookies": {"token": "secret-token", "__ddg3": "guard"},
                }
            )
        )


class _RecordingHttpClient:
    """Return one valid item page and capture transport headers."""

    def __init__(self) -> None:
        self.headers: dict[str, str] = {}

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        del url
        headers = kwargs.get("headers")
        assert isinstance(headers, dict)
        self.headers = headers
        return httpx.Response(
            200,
            json={
                "data": {
                    "items": {
                        "edges": [
                            {
                                "node": {
                                    "id": "offer-1",
                                    "slug": "minecraft-key",
                                    "name": "Minecraft Key",
                                    "price": 790,
                                }
                            }
                        ],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            },
        )
