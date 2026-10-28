"""Run one guarded live Playerok session-connector verification."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.http_client import HttpClient  # noqa: E402
from app.domain.marketplace_integrations import (  # noqa: E402
    MarketplaceAuthType,
    MarketplaceCredentialMetadata,
    MarketplaceIntegration,
)
from app.parsers.playerok_fetcher import PlayerokFetchError  # noqa: E402
from app.services.marketplace_credentials import (  # noqa: E402
    EnvironmentMarketplaceCredentialResolver,
    MarketplaceCredentialResolutionError,
)
from app.services.playerok_connector import (  # noqa: E402
    PlayerokConnector,
    PlayerokConnectorConfigurationError,
)

LIVE_GUARD = "I_UNDERSTAND_THIS_CONTACTS_PLAYEROK"


async def main() -> int:
    """Verify one explicitly configured session without printing credentials."""
    if os.getenv("PLAYEROK_LIVE_VERIFY", "") != LIVE_GUARD:
        print("SKIP: guarded Playerok live verification is disabled.")
        return 2

    try:
        tenant_id = UUID(_required_environment("PLAYEROK_VERIFY_TENANT_ID"))
        integration_id = UUID(_required_environment("PLAYEROK_VERIFY_INTEGRATION_ID"))
        source_url = _required_environment("PLAYEROK_VERIFY_SOURCE_URL")
        credential_reference = _required_environment(
            "PLAYEROK_VERIFY_CREDENTIAL_REFERENCE"
        )
        _validate_source_url(source_url)
    except (ValueError, RuntimeError) as exc:
        print(f"FAIL: invalid live-verification configuration ({exc}).")
        return 2

    now = datetime.now(UTC)
    integration = MarketplaceIntegration(
        id=integration_id,
        tenant_id=tenant_id,
        marketplace="playerok",
        display_name="Guarded Playerok live verification",
        source_url=source_url,
        auth_type=MarketplaceAuthType.SESSION,
        credential=MarketplaceCredentialMetadata(
            reference=credential_reference,
            configured_at=now,
        ),
        created_at=now,
        updated_at=now,
    )

    try:
        async with HttpClient(timeout=30.0, max_retries=1) as http_client:
            connector = PlayerokConnector(
                http_client=http_client,
                integration=integration,
                credential_resolver=EnvironmentMarketplaceCredentialResolver(),
            )
            offers = await connector.run(source_url)
    except PlayerokFetchError as exc:
        print(
            "FAIL: Playerok retrieval failed "
            f"(kind={exc.kind.value}, status={exc.status_code}, "
            f"retry_after={exc.retry_after_seconds})."
        )
        return 1
    except (
        MarketplaceCredentialResolutionError,
        PlayerokConnectorConfigurationError,
        ValueError,
    ) as exc:
        print(f"FAIL: Playerok connector configuration failed ({type(exc).__name__}).")
        return 2

    print(f"PASS: Playerok session connector returned {len(offers)} offers.")
    if offers:
        print(f"First offer ID: {offers[0].external_id or 'unavailable'}")
        print(f"First offer title: {offers[0].title or 'unavailable'}")
    return 0


def _required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _validate_source_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != "playerok.com":
        raise ValueError("source URL must use https://playerok.com")
    if parsed.path != "/graphql":
        raise ValueError("source URL must target the Playerok GraphQL endpoint")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
