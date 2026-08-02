from __future__ import annotations

from abc import abstractmethod
from uuid import UUID

from app.domain.price_snapshot import PriceSnapshot
from app.repositories.base import BaseRepository


class PriceHistoryRepository(BaseRepository):
    """Abstract storage contract for price snapshot history."""

    @abstractmethod
    async def add(self, tenant_id: UUID, snapshot: PriceSnapshot) -> bool:
        """Store a tenant-owned snapshot and return whether it was inserted."""

    @abstractmethod
    async def get_last(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
    ) -> PriceSnapshot | None:
        """Return the latest snapshot for one tenant-owned offer identity."""

    @abstractmethod
    async def get_previous(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
    ) -> PriceSnapshot | None:
        """Return the snapshot immediately before the latest tenant-owned row."""

    @abstractmethod
    async def get_history(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
    ) -> list[PriceSnapshot]:
        """Return tenant-owned snapshots in ascending collection-time order."""
