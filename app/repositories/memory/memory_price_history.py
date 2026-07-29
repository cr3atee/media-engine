from __future__ import annotations

from app.domain.price_snapshot import PriceSnapshot
from app.repositories.price_history import PriceHistoryRepository


class MemoryPriceHistoryRepository(PriceHistoryRepository):
    """In-memory repository for marketplace price snapshots."""

    def __init__(self) -> None:
        """Initialize empty price history storage."""
        self._storage: dict[tuple[str, str], list[PriceSnapshot]] = {}

    async def add(self, snapshot: PriceSnapshot) -> bool:
        """Store a snapshot and report whether it was newly inserted."""
        key = (snapshot.marketplace, snapshot.external_id)
        history = self._storage.setdefault(key, [])
        if snapshot in history:
            return False
        history.append(snapshot)
        return True

    async def get_last(
        self,
        marketplace: str,
        external_id: str,
    ) -> PriceSnapshot | None:
        """Return the latest stored snapshot for a marketplace offer."""
        history = await self.get_history(marketplace, external_id)
        if not history:
            return None
        return history[-1]

    async def get_previous(
        self,
        marketplace: str,
        external_id: str,
    ) -> PriceSnapshot | None:
        """Return the snapshot before the latest one for a marketplace offer."""
        history = await self.get_history(marketplace, external_id)
        if len(history) < 2:
            return None
        return history[-2]

    async def get_history(
        self,
        marketplace: str,
        external_id: str,
    ) -> list[PriceSnapshot]:
        """Return snapshots by collection time, then insertion order."""
        history = self._storage.get((marketplace, external_id), [])
        ordered = sorted(
            enumerate(history),
            key=lambda item: (item[1].collected_at, item[0]),
        )
        return [snapshot for _, snapshot in ordered]
