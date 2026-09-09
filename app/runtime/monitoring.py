from __future__ import annotations

from dataclasses import dataclass

from app.services.marketplace_application_runner import MarketplaceRunResult
from app.services.marketplace_integration_execution import (
    MarketplaceIntegrationExecution,
    MarketplaceIntegrationExecutionBatch,
)


@dataclass(slots=True, frozen=True)
class MarketplaceRunDiagnostic:
    """Safe operational summary for one marketplace application run."""

    offers_received: int
    offers_persisted: int
    snapshots_created: int
    snapshots_persisted: int
    price_changes_detected: int
    events_created: int
    errors: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class MarketplaceIntegrationDiagnostic:
    """Safe operational summary for one selected marketplace integration."""

    marketplace: str
    executed: bool
    source_url_present: bool
    skipped_reason: str | None
    result_type: str | None
    run: MarketplaceRunDiagnostic | None = None


@dataclass(slots=True, frozen=True)
class MarketplacePollingDiagnostic:
    """Safe operational summary for one enabled-integration polling batch."""

    selected_integrations: int
    executed_integrations: int
    skipped_integrations: int
    executions: tuple[MarketplaceIntegrationDiagnostic, ...]


class RuntimeMonitor:
    """Build safe runtime diagnostics from existing orchestration results."""

    def summarize_marketplace_batch(
        self,
        batch: MarketplaceIntegrationExecutionBatch,
    ) -> MarketplacePollingDiagnostic:
        """Summarize one marketplace integration execution batch."""
        return MarketplacePollingDiagnostic(
            selected_integrations=batch.selected_integrations,
            executed_integrations=batch.executed_integrations,
            skipped_integrations=batch.skipped_integrations,
            executions=tuple(
                self._summarize_execution(execution) for execution in batch.executions
            ),
        )

    def _summarize_execution(
        self,
        execution: MarketplaceIntegrationExecution,
    ) -> MarketplaceIntegrationDiagnostic:
        result = execution.result
        return MarketplaceIntegrationDiagnostic(
            marketplace=execution.marketplace,
            executed=execution.executed,
            source_url_present=execution.source_url is not None,
            skipped_reason=execution.skipped_reason,
            result_type=type(result).__name__ if result is not None else None,
            run=(
                self._summarize_marketplace_run(result)
                if isinstance(result, MarketplaceRunResult)
                else None
            ),
        )

    def _summarize_marketplace_run(
        self,
        result: MarketplaceRunResult,
    ) -> MarketplaceRunDiagnostic:
        return MarketplaceRunDiagnostic(
            offers_received=result.offers_received,
            offers_persisted=result.offers_persisted,
            snapshots_created=result.snapshots_created,
            snapshots_persisted=result.snapshots_persisted,
            price_changes_detected=result.price_changes_detected,
            events_created=result.events_created,
            errors=result.errors,
        )
