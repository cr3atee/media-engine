from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from app.domain.marketplace_polling import MarketplacePollingRun
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.marketplace_polling_runs import (
    MAX_POLLING_RUN_HISTORY,
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


def _validate_limit(limit: int) -> None:
    if not 1 <= limit <= MAX_POLLING_RUN_HISTORY:
        raise ValueError(
            f"Polling run limit must be between 1 and {MAX_POLLING_RUN_HISTORY}."
        )
