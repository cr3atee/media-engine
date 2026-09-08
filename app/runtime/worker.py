from __future__ import annotations

from collections.abc import Mapping

from app.runtime.process import RuntimeJobConfig, RuntimeProcess
from app.scheduler.jobs import EnabledMarketplaceIntegrationsJob
from app.services.marketplace_integration_execution import (
    MarketplaceIntegrationExecutionService,
    MarketplaceIntegrationRunnerFactory,
)


def register_enabled_marketplace_integrations_job(
    process: RuntimeProcess,
    *,
    runner_factories: Mapping[str, MarketplaceIntegrationRunnerFactory],
    config: RuntimeJobConfig | None = None,
) -> MarketplaceIntegrationExecutionService:
    """Register enabled marketplace integration execution in a runtime process."""
    service = MarketplaceIntegrationExecutionService(
        repository_scope_factory=process.components.repository_scope_factory,
        runner_factories=runner_factories,
    )
    process.register_job(
        EnabledMarketplaceIntegrationsJob(service),
        config,
    )
    return service
