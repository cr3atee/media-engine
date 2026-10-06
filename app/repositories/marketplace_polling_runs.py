from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from uuid import UUID

from app.domain.marketplace_polling import MarketplacePollingRun
from app.repositories.base import BaseRepository

MAX_POLLING_RUN_HISTORY = 100


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
