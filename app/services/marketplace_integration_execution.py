from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from app.domain.marketplace_integrations import MarketplaceIntegration
from app.domain.marketplace_polling import (
    MarketplacePollingRun,
    MarketplacePollingRunStatus,
)
from app.services.marketplace_application_runner import MarketplaceRunResult
from app.services.repository_scope import RepositoryScopeFactory


class MarketplaceIntegrationRunner(Protocol):
    """Application runner used for one selected marketplace integration."""

    async def run(self, url: str) -> object:
        """Run existing marketplace processing for one source URL."""


type MarketplaceIntegrationRunnerFactory = Callable[
    [MarketplaceIntegration],
    MarketplaceIntegrationRunner,
]
type PollingRunIdFactory = Callable[[], UUID]


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
    error_code: str | None = None
    error_summary: str | None = None
    polling_run_id: UUID | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def succeeded(self) -> bool:
        """Return whether the selected integration completed successfully."""
        return self.executed and self.error_code is None


@dataclass(slots=True, frozen=True)
class MarketplaceIntegrationExecutionBatch:
    """Summary of one enabled-integration orchestration batch."""

    selected_integrations: int
    executed_integrations: int
    skipped_integrations: int
    executions: tuple[MarketplaceIntegrationExecution, ...]

    @property
    def failed_integrations(self) -> int:
        """Return the number of attempted integrations that failed."""
        return sum(
            execution.executed and not execution.succeeded
            for execution in self.executions
        )


class MarketplaceIntegrationExecutionService:
    """Select tenant-owned marketplace integrations and delegate execution."""

    def __init__(
        self,
        *,
        repository_scope_factory: RepositoryScopeFactory,
        runner_factories: Mapping[str, MarketplaceIntegrationRunnerFactory],
        clock: Callable[[], datetime] | None = None,
        polling_run_id_factory: PollingRunIdFactory = uuid4,
    ) -> None:
        """Initialize the service with repositories and marketplace factories."""
        self._repository_scope_factory = repository_scope_factory
        self._runner_factories = {
            marketplace.lower(): factory
            for marketplace, factory in runner_factories.items()
        }
        self._clock = clock or _utc_now
        self._polling_run_id_factory = polling_run_id_factory

    async def run_enabled_integrations(self) -> MarketplaceIntegrationExecutionBatch:
        """Run enabled active integrations whose owning tenants are active."""
        selected = await self._select_integrations()
        executions: list[MarketplaceIntegrationExecution] = []

        for integration in selected:
            started_at = max(self._clock(), integration.created_at)
            polling_run_id = self._polling_run_id_factory()
            source_url = integration.source_url
            if source_url is None:
                execution = _skipped_execution(
                    integration,
                    "missing_source_url",
                    polling_run_id=polling_run_id,
                    started_at=started_at,
                    finished_at=max(self._clock(), started_at),
                )
                await self._record_execution(integration, execution)
                executions.append(execution)
                continue

            factory = self._runner_factories.get(integration.marketplace)
            if factory is None:
                execution = _skipped_execution(
                    integration,
                    "unsupported_marketplace",
                    polling_run_id=polling_run_id,
                    started_at=started_at,
                    finished_at=max(self._clock(), started_at),
                )
                await self._record_execution(integration, execution)
                executions.append(execution)
                continue

            runner = factory(integration)
            try:
                result = await runner.run(source_url)
            except Exception as exc:
                error_code = type(exc).__name__
                error_summary = "Marketplace polling failed."
                execution = MarketplaceIntegrationExecution(
                    integration_id=integration.id,
                    tenant_id=integration.tenant_id,
                    marketplace=integration.marketplace,
                    source_url=source_url,
                    executed=True,
                    error_code=error_code,
                    error_summary=error_summary,
                    polling_run_id=polling_run_id,
                    started_at=started_at,
                    finished_at=max(self._clock(), started_at),
                )
                await self._record_execution(integration, execution)
                executions.append(execution)
                continue

            execution = MarketplaceIntegrationExecution(
                integration_id=integration.id,
                tenant_id=integration.tenant_id,
                marketplace=integration.marketplace,
                source_url=source_url,
                executed=True,
                result=result,
                polling_run_id=polling_run_id,
                started_at=started_at,
                finished_at=max(self._clock(), started_at),
            )
            await self._record_execution(integration, execution)
            executions.append(execution)

        return MarketplaceIntegrationExecutionBatch(
            selected_integrations=len(selected),
            executed_integrations=sum(execution.executed for execution in executions),
            skipped_integrations=sum(
                not execution.executed for execution in executions
            ),
            executions=tuple(executions),
        )

    async def _record_execution(
        self,
        integration: MarketplaceIntegration,
        execution: MarketplaceIntegrationExecution,
    ) -> None:
        async with self._repository_scope_factory() as repositories:
            stored = await repositories.marketplace_integrations.get_by_tenant_and_id(
                integration.tenant_id,
                integration.id,
            )
            if stored is None:
                return
            if execution.executed:
                finished_at = _required_timestamp(execution.finished_at)
                occurred_at = max(finished_at, stored.updated_at)
                await repositories.marketplace_integrations.save(
                    replace(
                        stored,
                        last_successful_run_at=(
                            occurred_at
                            if execution.succeeded
                            else stored.last_successful_run_at
                        ),
                        last_failed_run_at=(
                            stored.last_failed_run_at
                            if execution.succeeded
                            else occurred_at
                        ),
                        last_error_code=(
                            None if execution.succeeded else execution.error_code
                        ),
                        last_error_summary=(
                            None if execution.succeeded else execution.error_summary
                        ),
                        updated_at=occurred_at,
                        version=stored.version + 1,
                    )
                )
            await repositories.marketplace_polling_runs.save(_to_polling_run(execution))

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
    *,
    polling_run_id: UUID,
    started_at: datetime,
    finished_at: datetime,
) -> MarketplaceIntegrationExecution:
    return MarketplaceIntegrationExecution(
        integration_id=integration.id,
        tenant_id=integration.tenant_id,
        marketplace=integration.marketplace,
        source_url=integration.source_url,
        executed=False,
        skipped_reason=reason,
        polling_run_id=polling_run_id,
        started_at=started_at,
        finished_at=finished_at,
    )


def _to_polling_run(
    execution: MarketplaceIntegrationExecution,
) -> MarketplacePollingRun:
    result = execution.result
    metrics = result if isinstance(result, MarketplaceRunResult) else None
    return MarketplacePollingRun(
        id=_required_run_id(execution.polling_run_id),
        tenant_id=execution.tenant_id,
        integration_id=execution.integration_id,
        marketplace=execution.marketplace,
        status=_run_status(execution),
        started_at=_required_timestamp(execution.started_at),
        finished_at=_required_timestamp(execution.finished_at),
        offers_received=metrics.offers_received if metrics is not None else None,
        offers_persisted=metrics.offers_persisted if metrics is not None else None,
        snapshots_created=metrics.snapshots_created if metrics is not None else None,
        snapshots_persisted=(
            metrics.snapshots_persisted if metrics is not None else None
        ),
        price_changes_detected=(
            metrics.price_changes_detected if metrics is not None else None
        ),
        events_created=metrics.events_created if metrics is not None else None,
        processing_error_count=len(metrics.errors) if metrics is not None else None,
        skipped_reason=execution.skipped_reason,
        error_code=execution.error_code,
        error_summary=execution.error_summary,
    )


def _run_status(
    execution: MarketplaceIntegrationExecution,
) -> MarketplacePollingRunStatus:
    if not execution.executed:
        return MarketplacePollingRunStatus.SKIPPED
    if execution.succeeded:
        return MarketplacePollingRunStatus.SUCCEEDED
    return MarketplacePollingRunStatus.FAILED


def _required_run_id(value: UUID | None) -> UUID:
    if value is None:
        raise RuntimeError("Marketplace polling run ID is missing.")
    return value


def _required_timestamp(value: datetime | None) -> datetime:
    if value is None:
        raise RuntimeError("Marketplace polling run timestamp is missing.")
    return value


def _utc_now() -> datetime:
    return datetime.now(UTC)
