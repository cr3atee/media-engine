from __future__ import annotations

from app.domain.price_snapshot import PriceSnapshot
from app.repositories.price_history import PriceHistoryRepository


class MemoryPriceHistoryRepository(PriceHistoryRepository):
    """In-memory repository for marketplace price snapshots."""

    def __init__(self) -> None:
        """Initialize empty price history storage."""
        self._storage: dict[tuple[str, str], list[PriceSnapshot]] = {}

    def add(self, snapshot: PriceSnapshot) -> None:
        """Store a price snapshot in insertion order."""
        key = (snapshot.marketplace, snapshot.external_id)
        self._storage.setdefault(key, []).append(snapshot)

    def get_last(
        self,
        marketplace: str,
        external_id: str,
    ) -> PriceSnapshot | None:
        """Return the latest stored snapshot for a marketplace offer."""
        history = self._storage.get((marketplace, external_id))
        if not history:
            return None
        return history[-1]

    def get_previous(
        self,
        marketplace: str,
        external_id: str,
    ) -> PriceSnapshot | None:
        """Return the snapshot before the latest one for a marketplace offer."""
        history = self._storage.get((marketplace, external_id))
        if history is None or len(history) < 2:
            return None
        return history[-2]

    def get_history(
        self,
        marketplace: str,
        external_id: str,
    ) -> list[PriceSnapshot]:
        """Return all stored snapshots for a marketplace offer."""
        return list(self._storage.get((marketplace, external_id), []))
