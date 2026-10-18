from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from app.domain.identity import normalize_utc
from app.repositories.marketplace_polling_runs import (
    MAX_POLLING_RUN_PRUNE_BATCH,
    MarketplacePollingRunPruneRequest,
)
from app.services.repository_scope import RepositoryScopeFactory


@dataclass(slots=True, frozen=True, kw_only=True)
class MarketplacePollingRetentionPolicy:
    """Explicit bounded policy for tenant-owned polling history retention."""

    retain_for: timedelta
    keep_latest_per_integration: int = 10
    batch_size: int = 500

    def __post_init__(self) -> None:
        if self.retain_for <= timedelta(0):
            raise ValueError("Polling retention period must be positive.")
        if self.keep_latest_per_integration < 1:
            raise ValueError("Polling retention must keep at least one run.")
        if not 1 <= self.batch_size <= MAX_POLLING_RUN_PRUNE_BATCH:
            raise ValueError(
                "Polling retention batch size must be between 1 and "
                f"{MAX_POLLING_RUN_PRUNE_BATCH}."
            )


@dataclass(slots=True, frozen=True, kw_only=True)
class MarketplacePollingRetentionResult:
    """Result of one bounded tenant retention pass."""

    tenant_id: UUID
    cutoff: datetime
    deleted_run_ids: tuple[UUID, ...]
    batch_limit_reached: bool

    @property
    def deleted_count(self) -> int:
        """Return the number of polling runs removed in this pass."""
        return len(self.deleted_run_ids)


@dataclass(slots=True, frozen=True, kw_only=True)
class MarketplacePollingRetentionBatch:
    """Results from one retention pass over tenants with polling history."""

    observed_at: datetime
    tenant_results: tuple[MarketplacePollingRetentionResult, ...]

    @property
    def tenant_count(self) -> int:
        """Return the number of tenant histories inspected."""
        return len(self.tenant_results)

    @property
    def deleted_count(self) -> int:
        """Return the total number of polling runs removed."""
        return sum(result.deleted_count for result in self.tenant_results)

    @property
    def batch_limit_reached(self) -> bool:
        """Report whether any tenant may need another bounded pass."""
        return any(result.batch_limit_reached for result in self.tenant_results)


class MarketplacePollingRetentionService:
    """Apply polling-history retention through one repository transaction."""

    def __init__(
        self,
        *,
        repository_scope_factory: RepositoryScopeFactory,
        policy: MarketplacePollingRetentionPolicy,
    ) -> None:
        self._repository_scope_factory = repository_scope_factory
        self._policy = policy

    async def prune(
        self,
        tenant_id: UUID,
        *,
        now: datetime,
    ) -> MarketplacePollingRetentionResult:
        """Delete one bounded batch older than the configured retention period."""
        observed_at = normalize_utc(now, field_name="now")
        try:
            cutoff = observed_at - self._policy.retain_for
        except OverflowError as error:
            raise ValueError(
                "Polling retention cutoff is outside datetime range."
            ) from error
        request = MarketplacePollingRunPruneRequest(
            tenant_id=tenant_id,
            cutoff=cutoff,
            keep_latest_per_integration=self._policy.keep_latest_per_integration,
            limit=self._policy.batch_size,
        )
        async with self._repository_scope_factory() as repositories:
            deleted_ids = tuple(
                await repositories.marketplace_polling_runs.prune_by_tenant(request)
            )
        return MarketplacePollingRetentionResult(
            tenant_id=tenant_id,
            cutoff=cutoff,
            deleted_run_ids=deleted_ids,
            batch_limit_reached=len(deleted_ids) == self._policy.batch_size,
        )

    async def prune_all(self, *, now: datetime) -> MarketplacePollingRetentionBatch:
        """Prune one bounded batch for every tenant that owns polling history."""
        observed_at = normalize_utc(now, field_name="now")
        async with self._repository_scope_factory() as repositories:
            tenant_ids = tuple(
                await repositories.marketplace_polling_runs.list_tenant_ids()
            )
        tenant_results: list[MarketplacePollingRetentionResult] = []
        for tenant_id in tenant_ids:
            tenant_results.append(await self.prune(tenant_id, now=observed_at))
        return MarketplacePollingRetentionBatch(
            observed_at=observed_at,
            tenant_results=tuple(tenant_results),
        )
