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
from app.domain.marketplace_polling import MarketplacePollingRunStatus
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


class FailingRunner:
    """Runner double used to verify per-integration failure isolation."""

    async def run(self, url: str) -> object:
        """Fail without exposing the source URL through diagnostics."""
        raise RuntimeError(f"secret source failed: {url}")


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
        for execution, expected_status in zip(
            batch.executions,
            (
                MarketplacePollingRunStatus.SUCCEEDED,
                MarketplacePollingRunStatus.SKIPPED,
                MarketplacePollingRunStatus.SKIPPED,
            ),
            strict=True,
        ):
            history = await provider.marketplace_polling_runs.list_by_integration(
                execution.tenant_id,
                execution.integration_id,
                limit=10,
            )
            assert len(history) == 1
            assert history[0].status is expected_status

    run_async(scenario())


def test_scheduler_job_delegates_to_enabled_integration_service() -> None:
    service = RecordingExecutionService()
    job = EnabledMarketplaceIntegrationsJob(service)

    run_async(job.execute())

    assert service.calls == 1
    assert job.status.state is JobExecutionState.SUCCEEDED


def test_execution_service_isolates_failures_and_persists_outcomes() -> None:
    provider = create_memory_provider()
    calls: list[RunnerCall] = []
    completed_at = NOW + timedelta(hours=1)

    async def scenario() -> None:
        await provider.tenants.create(
            make_tenant(tenant_id=TENANT_A_ID, slug="tenant-a"),
        )
        failed = make_integration(number=7, marketplace="ggsel")
        succeeded = make_integration(number=8, marketplace="playerok")
        await provider.marketplace_integrations.save(failed)
        await provider.marketplace_integrations.save(succeeded)

        service = MarketplaceIntegrationExecutionService(
            repository_scope_factory=create_memory_repository_scope(provider),
            runner_factories={
                "ggsel": lambda integration: FailingRunner(),
                "playerok": lambda integration: RecordingRunner(integration, calls),
            },
            clock=lambda: completed_at,
        )
        batch = await service.run_enabled_integrations()

        assert batch.selected_integrations == 2
        assert batch.executed_integrations == 2
        assert batch.skipped_integrations == 0
        assert batch.failed_integrations == 1
        assert batch.executions[0].error_code == "RuntimeError"
        assert batch.executions[0].error_summary == "Marketplace polling failed."
        assert batch.executions[1].succeeded is True
        assert len(calls) == 1

        stored_failed = await provider.marketplace_integrations.get_by_tenant_and_id(
            TENANT_A_ID,
            failed.id,
        )
        stored_succeeded = await provider.marketplace_integrations.get_by_tenant_and_id(
            TENANT_A_ID,
            succeeded.id,
        )
        assert stored_failed is not None
        assert stored_failed.last_failed_run_at == completed_at
        assert stored_failed.last_error_code == "RuntimeError"
        assert stored_failed.last_error_summary == "Marketplace polling failed."
        assert stored_failed.version == 2
        assert stored_succeeded is not None
        assert stored_succeeded.last_successful_run_at == completed_at
        assert stored_succeeded.last_error_code is None
        assert stored_succeeded.version == 2
        failed_history = await provider.marketplace_polling_runs.list_by_integration(
            TENANT_A_ID,
            failed.id,
            limit=10,
        )
        successful_history = (
            await provider.marketplace_polling_runs.list_by_integration(
                TENANT_A_ID,
                succeeded.id,
                limit=10,
            )
        )
        assert failed_history[0].status is MarketplacePollingRunStatus.FAILED
        assert failed_history[0].error_code == "RuntimeError"
        assert "secret" not in (failed_history[0].error_summary or "")
        assert successful_history[0].status is MarketplacePollingRunStatus.SUCCEEDED

        recovered_at = completed_at + timedelta(hours=1)
        recovery_service = MarketplaceIntegrationExecutionService(
            repository_scope_factory=create_memory_repository_scope(provider),
            runner_factories={
                "ggsel": lambda integration: RecordingRunner(integration, calls),
                "playerok": lambda integration: RecordingRunner(integration, calls),
            },
            clock=lambda: recovered_at,
        )
        recovery_batch = await recovery_service.run_enabled_integrations()
        recovered = await provider.marketplace_integrations.get_by_tenant_and_id(
            TENANT_A_ID,
            failed.id,
        )

        assert recovery_batch.failed_integrations == 0
        assert recovered is not None
        assert recovered.last_failed_run_at == completed_at
        assert recovered.last_successful_run_at == recovered_at
        assert recovered.last_error_code is None
        assert recovered.last_error_summary is None
        assert recovered.version == 3
        recovered_history = await provider.marketplace_polling_runs.list_by_integration(
            TENANT_A_ID,
            failed.id,
            limit=10,
        )
        assert [run.status for run in recovered_history] == [
            MarketplacePollingRunStatus.SUCCEEDED,
            MarketplacePollingRunStatus.FAILED,
        ]

    run_async(scenario())
