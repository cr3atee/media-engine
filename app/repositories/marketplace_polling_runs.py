from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.identity import normalize_utc
from app.domain.marketplace_polling import MarketplacePollingRun
from app.repositories.base import BaseRepository

MAX_POLLING_RUN_HISTORY = 100
MAX_POLLING_RUN_PRUNE_BATCH = 1_000


@dataclass(slots=True, frozen=True, kw_only=True)
class MarketplacePollingRunPruneRequest:
    """Bounded tenant-scoped request for deleting expired polling runs."""

    tenant_id: UUID
    cutoff: datetime
    keep_latest_per_integration: int
    limit: int

    def __post_init__(self) -> None:
        if self.keep_latest_per_integration < 1:
            raise ValueError("Polling retention must keep at least one run.")
        if not 1 <= self.limit <= MAX_POLLING_RUN_PRUNE_BATCH:
            raise ValueError(
                "Polling prune limit must be between 1 and "
                f"{MAX_POLLING_RUN_PRUNE_BATCH}."
            )
        object.__setattr__(
            self,
            "cutoff",
            normalize_utc(self.cutoff, field_name="cutoff"),
        )


class MarketplacePollingRunRepository(BaseRepository):
    """Storage contract for immutable marketplace polling history."""

    @abstractmethod
    async def save(self, run: MarketplacePollingRun) -> MarketplacePollingRun:
        """Persist one immutable polling run."""

    @abstractmethod
    async def list_by_integration(
        self,
        tenant_id: UUID,
        integration_id: UUID,
        *,
        limit: int,
    ) -> Sequence[MarketplacePollingRun]:
        """Return newest runs for one tenant-owned integration."""

    @abstractmethod
    async def prune_by_tenant(
        self,
        request: MarketplacePollingRunPruneRequest,
    ) -> Sequence[UUID]:
        """Delete one deterministic batch of expired tenant-owned runs."""
