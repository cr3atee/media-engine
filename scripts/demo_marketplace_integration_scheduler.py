"""Demonstrate enabled marketplace integration Scheduler selection."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.domain.marketplace_integrations import (
    MarketplaceIntegration,
    MarketplaceIntegrationStatus,
)
from app.domain.tenancy import Tenant
from app.repositories.provider import create_memory_provider
from app.scheduler.jobs import EnabledMarketplaceIntegrationsJob
from app.scheduler.service import SchedulerService
from app.services.marketplace_integration_execution import (
    MarketplaceIntegrationExecutionService,
)
from app.services.repository_scope import create_memory_repository_scope

TENANT_ID = UUID("10000000-0000-4000-8000-000000000301")
NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


@dataclass(slots=True)
class DemoRunner:
    """Small runner double that avoids real marketplace network calls."""

    integration: MarketplaceIntegration

    async def run(self, url: str) -> str:
        """Return a readable execution summary."""
        return f"{self.integration.marketplace} executed for {url}"


async def main() -> None:
    """Run one Scheduler-driven integration selection demo."""
    provider = create_memory_provider()
    await provider.tenants.create(
        Tenant(
            id=TENANT_ID,
            name="Demo Tenant",
            slug="demo-tenant",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await provider.marketplace_integrations.save(
        _integration(number=1, marketplace="ggsel"),
    )
    await provider.marketplace_integrations.save(
        _integration(
            number=2, marketplace="playerok", source_url="https://playerok.com"
        ),
    )
    await provider.marketplace_integrations.save(
        _integration(
            number=3,
            source_url="https://ggsel.net/catalog/disabled",
            enabled=False,
        ),
    )
    await provider.marketplace_integrations.save(
        _integration(
            number=4,
            source_url="https://ggsel.net/catalog/draft",
            status=MarketplaceIntegrationStatus.DRAFT,
        ),
    )

    service = MarketplaceIntegrationExecutionService(
        repository_scope_factory=create_memory_repository_scope(provider),
        runner_factories={
            "ggsel": DemoRunner,
            "playerok": DemoRunner,
        },
    )
    selected = await service.run_enabled_integrations()
    print("=== ENABLED INTEGRATION SELECTION ===")
    print(f"Selected: {selected.selected_integrations}")
    print(f"Executed: {selected.executed_integrations}")
    print(f"Skipped: {selected.skipped_integrations}")
    for execution in selected.executions:
        print(
            f"{execution.marketplace}: executed={execution.executed} "
            f"url={execution.source_url} reason={execution.skipped_reason}"
        )

    job = EnabledMarketplaceIntegrationsJob(service)
    scheduler = SchedulerService()

    scheduler.register_job(job)
    await scheduler.execute_job(job.name)
    await scheduler.stop()

    status = job.status
    print("=== SCHEDULER JOB ===")
    print(f"Job: {status.name}")
    print(f"Status: {status.state}")
    print(f"Runs: {status.run_count}")


def _integration(
    *,
    number: int,
    marketplace: str = "ggsel",
    source_url: str | None = "https://ggsel.net/catalog/minecraft",
    enabled: bool = True,
    status: MarketplaceIntegrationStatus = MarketplaceIntegrationStatus.ACTIVE,
) -> MarketplaceIntegration:
    timestamp = NOW + timedelta(minutes=number)
    return MarketplaceIntegration(
        id=UUID(int=19_300 + number),
        tenant_id=TENANT_ID,
        marketplace=marketplace,
        display_name=f"{marketplace} {number}",
        enabled=enabled,
        status=status,
        source_url=source_url,
        created_at=timestamp,
        updated_at=timestamp,
    )


if __name__ == "__main__":
    asyncio.run(main())
