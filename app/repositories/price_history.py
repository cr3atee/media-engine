from __future__ import annotations

from abc import abstractmethod

from app.domain.price_snapshot import PriceSnapshot
from app.repositories.base import BaseRepository


class PriceHistoryRepository(BaseRepository):
    """Abstract storage contract for price snapshot history."""

    @abstractmethod
    async def add(self, snapshot: PriceSnapshot) -> bool:
        """Store a snapshot and return whether a new record was inserted."""

    @abstractmethod
    async def get_last(
        self,
        marketplace: str,
        external_id: str,
    ) -> PriceSnapshot | None:
        """Return the chronologically latest snapshot for an offer identity."""

    @abstractmethod
    async def get_previous(
        self,
        marketplace: str,
        external_id: str,
    ) -> PriceSnapshot | None:
        """Return the snapshot immediately before the latest one."""

    @abstractmethod
    async def get_history(
        self,
        marketplace: str,
        external_id: str,
    ) -> list[PriceSnapshot]:
        """Return snapshots in ascending collection-time order."""
