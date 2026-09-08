from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.http_client import HttpClient
from app.domain.marketplace import Marketplace
from app.domain.marketplace_integrations import MarketplaceIntegration
from app.repositories.provider import create_memory_provider
from app.runtime.marketplaces import create_marketplace_runner_factories
from app.services.marketplace_application_runner import MarketplaceApplicationRunner
from app.services.repository_scope import create_memory_repository_scope


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run async runtime marketplace checks without an external plugin."""
    return asyncio.run(awaitable)


def make_integration(marketplace: Marketplace) -> MarketplaceIntegration:
    """Create a minimal marketplace integration for runner factory tests."""
    now = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    return MarketplaceIntegration(
        id=UUID(int=24_001),
        tenant_id=UUID("10000000-0000-4000-8000-000000000501"),
        marketplace=marketplace.value,
        display_name=marketplace.value,
        source_url="https://example.com/catalog",
        created_at=now,
        updated_at=now,
    )


def test_runtime_marketplace_factories_cover_supported_marketplaces() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        async with HttpClient() as http_client:
            factories = create_marketplace_runner_factories(
                http_client=http_client,
                repository_scope_factory=create_memory_repository_scope(provider),
            )

            assert set(factories) == {
                Marketplace.GGSEL.value,
                Marketplace.PLAYEROK.value,
                Marketplace.FUNPAY.value,
            }
            for marketplace in Marketplace:
                runner = factories[marketplace.value](make_integration(marketplace))
                assert isinstance(runner, MarketplaceApplicationRunner)

    run_async(scenario())
