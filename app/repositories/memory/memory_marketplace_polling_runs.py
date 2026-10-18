from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from app.domain.marketplace_polling import MarketplacePollingRun
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.marketplace_polling_runs import (
    MAX_POLLING_RUN_HISTORY,
    MarketplacePollingRunPruneRequest,
    MarketplacePollingRunRepository,
)


class MemoryMarketplacePollingRunRepository(MarketplacePollingRunRepository):
    """Deterministic in-memory storage for immutable polling history."""

    def __init__(self) -> None:
        self._runs_by_id: dict[UUID, MarketplacePollingRun] = {}

    async def save(self, run: MarketplacePollingRun) -> MarketplacePollingRun:
        """Persist an immutable run or replay the identical value."""
        existing = self._runs_by_id.get(run.id)
        if existing is not None and existing != run:
            raise RepositoryIdentityConflictError(
                f"Marketplace polling run ID already exists: {run.id}."
            )
        self._runs_by_id[run.id] = run
        return run

    async def list_by_integration(
        self,
        tenant_id: UUID,
        integration_id: UUID,
        *,
        limit: int,
    ) -> Sequence[MarketplacePollingRun]:
        """Return newest tenant-scoped runs with deterministic tie-breaking."""
        _validate_limit(limit)
        matching = (
            run
            for run in self._runs_by_id.values()
            if run.tenant_id == tenant_id and run.integration_id == integration_id
        )
        return tuple(
            sorted(
                matching,
                key=lambda run: (run.finished_at, run.id),
                reverse=True,
            )[:limit]
        )

    async def prune_by_tenant(
        self,
        request: MarketplacePollingRunPruneRequest,
    ) -> Sequence[UUID]:
        """Delete oldest expired runs while preserving recent integration runs."""
        tenant_runs = tuple(
            run
            for run in self._runs_by_id.values()
            if run.tenant_id == request.tenant_id
        )
        runs_by_integration: dict[UUID, list[MarketplacePollingRun]] = {}
        for run in tenant_runs:
            runs_by_integration.setdefault(run.integration_id, []).append(run)

        protected_ids: set[UUID] = set()
        for runs in runs_by_integration.values():
            newest = sorted(
                runs,
                key=lambda run: (run.finished_at, run.id),
                reverse=True,
            )[: request.keep_latest_per_integration]
            protected_ids.update(run.id for run in newest)

        eligible = sorted(
            (
                run
                for run in tenant_runs
                if run.id not in protected_ids and run.finished_at < request.cutoff
            ),
            key=lambda run: (run.finished_at, run.id),
        )[: request.limit]
        deleted_ids = tuple(run.id for run in eligible)
        for run_id in deleted_ids:
            del self._runs_by_id[run_id]
        return deleted_ids


def _validate_limit(limit: int) -> None:
    if not 1 <= limit <= MAX_POLLING_RUN_HISTORY:
        raise ValueError(
            f"Polling run limit must be between 1 and {MAX_POLLING_RUN_HISTORY}."
        )
