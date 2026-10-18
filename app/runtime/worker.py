from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta

from app.runtime.process import RuntimeJobConfig, RuntimeProcess
from app.scheduler.jobs import (
    EnabledMarketplaceIntegrationsJob,
    MarketplacePollingRetentionJob,
)
from app.services.marketplace_integration_execution import (
    MarketplaceIntegrationExecutionService,
    MarketplaceIntegrationRunnerFactory,
)
from app.services.marketplace_polling_retention import (
    MarketplacePollingRetentionPolicy,
    MarketplacePollingRetentionService,
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


def register_marketplace_polling_retention_job(
    process: RuntimeProcess,
    *,
    retain_for_seconds: int,
    keep_latest_per_integration: int,
    batch_size: int,
    config: RuntimeJobConfig,
) -> MarketplacePollingRetentionService:
    """Register scheduled retention with an explicit deployment-owned policy."""
    service = MarketplacePollingRetentionService(
        repository_scope_factory=process.components.repository_scope_factory,
        policy=MarketplacePollingRetentionPolicy(
            retain_for=timedelta(seconds=retain_for_seconds),
            keep_latest_per_integration=keep_latest_per_integration,
            batch_size=batch_size,
        ),
    )
    process.register_job(MarketplacePollingRetentionJob(service), config)
    return service
