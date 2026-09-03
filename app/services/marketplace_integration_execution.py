from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.domain.marketplace_integrations import MarketplaceIntegration
from app.services.repository_scope import RepositoryScopeFactory


class MarketplaceIntegrationRunner(Protocol):
    """Application runner used for one selected marketplace integration."""

    async def run(self, url: str) -> object:
        """Run existing marketplace processing for one source URL."""


type MarketplaceIntegrationRunnerFactory = Callable[
    [MarketplaceIntegration],
    MarketplaceIntegrationRunner,
]


@dataclass(slots=True, frozen=True)
class MarketplaceIntegrationExecution:
    """Execution summary for one selected marketplace integration."""

    integration_id: UUID
    tenant_id: UUID
    marketplace: str
    source_url: str | None
    executed: bool
    skipped_reason: str | None = None
    result: object | None = None


@dataclass(slots=True, frozen=True)
class MarketplaceIntegrationExecutionBatch:
    """Summary of one enabled-integration orchestration batch."""

    selected_integrations: int
    executed_integrations: int
    skipped_integrations: int
    executions: tuple[MarketplaceIntegrationExecution, ...]


class MarketplaceIntegrationExecutionService:
    """Select tenant-owned marketplace integrations and delegate execution."""

    def __init__(
        self,
        *,
        repository_scope_factory: RepositoryScopeFactory,
        runner_factories: Mapping[str, MarketplaceIntegrationRunnerFactory],
    ) -> None:
        """Initialize the service with repositories and marketplace factories."""
        self._repository_scope_factory = repository_scope_factory
        self._runner_factories = {
            marketplace.lower(): factory
            for marketplace, factory in runner_factories.items()
        }

    async def run_enabled_integrations(self) -> MarketplaceIntegrationExecutionBatch:
        """Run enabled active integrations whose owning tenants are active."""
        selected = await self._select_integrations()
        executions: list[MarketplaceIntegrationExecution] = []

        for integration in selected:
            source_url = integration.source_url
            if source_url is None:
                executions.append(
                    _skipped_execution(integration, "missing_source_url"),
                )
                continue

            factory = self._runner_factories.get(integration.marketplace)
            if factory is None:
                executions.append(
                    _skipped_execution(integration, "unsupported_marketplace"),
                )
                continue

            runner = factory(integration)
            executions.append(
                MarketplaceIntegrationExecution(
                    integration_id=integration.id,
                    tenant_id=integration.tenant_id,
                    marketplace=integration.marketplace,
                    source_url=source_url,
                    executed=True,
                    result=await runner.run(source_url),
                ),
            )

        return MarketplaceIntegrationExecutionBatch(
            selected_integrations=len(selected),
            executed_integrations=sum(execution.executed for execution in executions),
            skipped_integrations=sum(
                not execution.executed for execution in executions
            ),
            executions=tuple(executions),
        )

    async def _select_integrations(self) -> tuple[MarketplaceIntegration, ...]:
        async with self._repository_scope_factory() as repositories:
            integrations = await repositories.marketplace_integrations.list_enabled()
            selected: list[MarketplaceIntegration] = []
            for integration in integrations:
                tenant = await repositories.tenants.get_by_id(integration.tenant_id)
                if tenant is not None and tenant.is_active:
                    selected.append(integration)
            return tuple(selected)


def _skipped_execution(
    integration: MarketplaceIntegration,
    reason: str,
) -> MarketplaceIntegrationExecution:
    return MarketplaceIntegrationExecution(
        integration_id=integration.id,
        tenant_id=integration.tenant_id,
        marketplace=integration.marketplace,
        source_url=integration.source_url,
        executed=False,
        skipped_reason=reason,
    )
