from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from app.domain.marketplace_integrations import (
    MarketplaceIntegration,
    MarketplaceIntegrationStatus,
)
from app.domain.tenancy import Tenant
from app.repositories.provider import create_memory_provider
from app.scheduler.jobs import EnabledMarketplaceIntegrationsJob, JobExecutionState
from app.services.marketplace_integration_execution import (
    MarketplaceIntegrationExecutionService,
)
from app.services.repository_scope import create_memory_repository_scope

TENANT_A_ID = UUID("10000000-0000-4000-8000-000000000101")
TENANT_B_ID = UUID("10000000-0000-4000-8000-000000000102")
NOW = datetime(2026, 9, 3, 9, 0, tzinfo=UTC)


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run async service methods without requiring a pytest plugin."""
    return asyncio.run(awaitable)


@dataclass(slots=True)
class RunnerCall:
    """Captured marketplace integration execution input."""

    tenant_id: UUID
    integration_id: UUID
    marketplace: str
    source_url: str


class RecordingRunner:
    """Runner double that records the selected integration context."""

    def __init__(
        self,
        integration: MarketplaceIntegration,
        calls: list[RunnerCall],
    ) -> None:
        self._integration = integration
        self._calls = calls

    async def run(self, url: str) -> str:
        """Record one delegated marketplace run."""
        self._calls.append(
            RunnerCall(
                tenant_id=self._integration.tenant_id,
                integration_id=self._integration.id,
                marketplace=self._integration.marketplace,
                source_url=url,
            )
        )
        return f"ran:{self._integration.marketplace}:{url}"


class RecordingExecutionService:
    """Service double used to verify Scheduler job delegation."""

    def __init__(self) -> None:
        self.calls = 0

    async def run_enabled_integrations(self) -> object:
        """Record one delegated execution batch."""
        self.calls += 1
        return {"executed": True}


def make_tenant(
    *,
    tenant_id: UUID,
    slug: str,
    is_active: bool = True,
) -> Tenant:
    """Create deterministic tenant data for selection tests."""
    return Tenant(
        id=tenant_id,
        name=slug,
        slug=slug,
        is_active=is_active,
        created_at=NOW,
        updated_at=NOW,
    )


def make_integration(
    *,
    number: int,
    tenant_id: UUID = TENANT_A_ID,
    marketplace: str = "ggsel",
    source_url: str | None = "https://ggsel.net/catalog/minecraft",
    enabled: bool = True,
    status: MarketplaceIntegrationStatus = MarketplaceIntegrationStatus.ACTIVE,
) -> MarketplaceIntegration:
    """Create deterministic marketplace integration test data."""
    return MarketplaceIntegration(
        id=UUID(int=17_100 + number),
        tenant_id=tenant_id,
        marketplace=marketplace,
        display_name=f"{marketplace} {number}",
        enabled=enabled,
        status=status,
        source_url=source_url,
        created_at=NOW + timedelta(minutes=number),
        updated_at=NOW + timedelta(minutes=number),
    )


def test_execution_service_runs_only_enabled_integrations_for_active_tenants() -> None:
    provider = create_memory_provider()
    calls: list[RunnerCall] = []

    async def scenario() -> None:
        await provider.tenants.create(
            make_tenant(tenant_id=TENANT_A_ID, slug="tenant-a"),
        )
        await provider.tenants.create(
            make_tenant(tenant_id=TENANT_B_ID, slug="tenant-b", is_active=False),
        )
        await provider.marketplace_integrations.save(make_integration(number=1))
        await provider.marketplace_integrations.save(
            make_integration(
                number=2,
                enabled=False,
                source_url="https://ggsel.net/catalog/disabled-flag",
            ),
        )
        await provider.marketplace_integrations.save(
            make_integration(
                number=3,
                status=MarketplaceIntegrationStatus.DISABLED,
                source_url="https://ggsel.net/catalog/disabled-status",
            ),
        )
        await provider.marketplace_integrations.save(
            make_integration(
                number=4,
                tenant_id=TENANT_B_ID,
                source_url="https://ggsel.net/catalog/inactive-tenant",
            ),
        )
        await provider.marketplace_integrations.save(
            make_integration(number=5, source_url=None),
        )
        await provider.marketplace_integrations.save(
            make_integration(
                number=6,
                marketplace="future-market",
                source_url="https://example.com/future",
            ),
        )

        service = MarketplaceIntegrationExecutionService(
            repository_scope_factory=create_memory_repository_scope(provider),
            runner_factories={
                "ggsel": lambda integration: RecordingRunner(integration, calls),
            },
        )
        batch = await service.run_enabled_integrations()

        assert batch.selected_integrations == 3
        assert batch.executed_integrations == 1
        assert batch.skipped_integrations == 2
        assert calls == [
            RunnerCall(
                tenant_id=TENANT_A_ID,
                integration_id=UUID(int=17_101),
                marketplace="ggsel",
                source_url="https://ggsel.net/catalog/minecraft",
            )
        ]
        assert [execution.skipped_reason for execution in batch.executions[1:]] == [
            "missing_source_url",
            "unsupported_marketplace",
        ]

    run_async(scenario())


def test_scheduler_job_delegates_to_enabled_integration_service() -> None:
    service = RecordingExecutionService()
    job = EnabledMarketplaceIntegrationsJob(service)

    run_async(job.execute())

    assert service.calls == 1
    assert job.status.state is JobExecutionState.SUCCEEDED
