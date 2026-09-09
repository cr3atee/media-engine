from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.config.settings import SchedulerSettings
from app.domain.marketplace_integrations import (
    MarketplaceIntegration,
    MarketplaceIntegrationStatus,
)
from app.domain.tenancy import Tenant
from app.runtime.bootstrap import create_memory_runtime_components
from app.runtime.process import RuntimeJobConfig, RuntimeProcess
from app.runtime.worker import register_enabled_marketplace_integrations_job
from app.scheduler.jobs import JobExecutionState
from app.services.marketplace_integration_execution import (
    MarketplaceIntegrationExecutionBatch,
)


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run async runtime worker checks without an external pytest plugin."""
    return asyncio.run(awaitable)


def test_worker_registers_enabled_marketplace_integrations_job() -> None:
    process = RuntimeProcess(
        create_memory_runtime_components(
            SchedulerSettings(lease_enabled=False, tick_seconds=0.1),
        ),
    )

    register_enabled_marketplace_integrations_job(
        process,
        runner_factories={},
        config=RuntimeJobConfig(interval_seconds=60, enabled=False),
    )

    assert process.list_statuses()[0].name == "enabled-marketplace-integrations"
    assert process.list_statuses()[0].state is JobExecutionState.REGISTERED
    assert process.list_schedule_statuses()[0].interval_seconds == 60


def test_worker_job_delegates_to_integration_service() -> None:
    components = create_memory_runtime_components(
        SchedulerSettings(lease_enabled=False, tick_seconds=0.1),
    )
    process = RuntimeProcess(components)

    async def scenario() -> None:
        tenant_id = UUID("10000000-0000-4000-8000-000000000601")
        now = datetime(2026, 9, 9, 10, 0, tzinfo=UTC)
        async with components.repository_scope_factory() as repositories:
            await repositories.tenants.create(
                Tenant(
                    id=tenant_id,
                    name="Tenant",
                    slug="tenant",
                    created_at=now,
                    updated_at=now,
                )
            )
            await repositories.marketplace_integrations.save(
                MarketplaceIntegration(
                    id=UUID("10000000-0000-4000-8000-000000000602"),
                    tenant_id=tenant_id,
                    marketplace="ggsel",
                    display_name="GGSEL",
                    source_url="https://ggsel.net/catalog",
                    enabled=True,
                    status=MarketplaceIntegrationStatus.ACTIVE,
                    created_at=now,
                    updated_at=now,
                )
            )

    run_async(scenario())

    register_enabled_marketplace_integrations_job(process, runner_factories={})

    run_async(process.execute_once("enabled-marketplace-integrations"))

    result = process.get_last_result("enabled-marketplace-integrations")

    assert process.list_statuses()[0].state is JobExecutionState.SUCCEEDED
    assert isinstance(result, MarketplaceIntegrationExecutionBatch)
    assert result.selected_integrations == 1
    assert result.skipped_integrations == 1


def test_worker_job_handles_empty_integration_selection() -> None:
    process = RuntimeProcess(
        create_memory_runtime_components(
            SchedulerSettings(lease_enabled=False, tick_seconds=0.1),
        ),
    )
    register_enabled_marketplace_integrations_job(process, runner_factories={})

    run_async(process.execute_once("enabled-marketplace-integrations"))

    assert process.list_statuses()[0].state is JobExecutionState.SUCCEEDED
