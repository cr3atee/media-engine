from __future__ import annotations

from abc import abstractmethod

from app.domain.price_snapshot import PriceSnapshot
from app.repositories.base import BaseRepository


class PriceHistoryRepository(BaseRepository):
    """Abstract storage contract for price snapshot history."""

    @abstractmethod
    def add(self, snapshot: PriceSnapshot) -> None:
        """Store a price snapshot."""

    @abstractmethod
    def get_last(
        self,
        marketplace: str,
        external_id: str,
    ) -> PriceSnapshot | None:
        """Return the latest snapshot for a marketplace offer."""

    @abstractmethod
    def get_previous(
        self,
        marketplace: str,
        external_id: str,
    ) -> PriceSnapshot | None:
        """Return the snapshot before the latest one for a marketplace offer."""

    @abstractmethod
    def get_history(
        self,
        marketplace: str,
        external_id: str,
    ) -> list[PriceSnapshot]:
        """Return all snapshots for a marketplace offer."""
