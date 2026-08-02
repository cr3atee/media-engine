from __future__ import annotations

from uuid import UUID

from app.domain.price_snapshot import PriceSnapshot
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.price_history import PriceHistoryRepository


class MemoryPriceHistoryRepository(PriceHistoryRepository):
    """In-memory repository for marketplace price snapshots."""

    def __init__(self) -> None:
        """Initialize empty price history storage."""
        self._storage: dict[tuple[UUID, str, str], list[PriceSnapshot]] = {}

    async def add(self, tenant_id: UUID, snapshot: PriceSnapshot) -> bool:
        """Store a snapshot and report whether it was newly inserted."""
        _validate_tenant(tenant_id, snapshot.tenant_id)
        key = (tenant_id, snapshot.marketplace, snapshot.external_id)
        history = self._storage.setdefault(key, [])
        if snapshot in history:
            return False
        history.append(snapshot)
        return True

    async def get_last(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
    ) -> PriceSnapshot | None:
        """Return the latest stored snapshot for a marketplace offer."""
        history = await self.get_history(tenant_id, marketplace, external_id)
        if not history:
            return None
        return history[-1]

    async def get_previous(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
    ) -> PriceSnapshot | None:
        """Return the snapshot before the latest one for a marketplace offer."""
        history = await self.get_history(tenant_id, marketplace, external_id)
        if len(history) < 2:
            return None
        return history[-2]

    async def get_history(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
    ) -> list[PriceSnapshot]:
        """Return snapshots by collection time, then insertion order."""
        history = self._storage.get((tenant_id, marketplace, external_id), [])
        ordered = sorted(
            enumerate(history),
            key=lambda item: (item[1].collected_at, item[0]),
        )
        return [snapshot for _, snapshot in ordered]


def _validate_tenant(requested: UUID, actual: UUID) -> None:
    if requested != actual:
        msg = f"Snapshot tenant mismatch: requested {requested}, got {actual}."
        raise RepositoryIdentityConflictError(msg)
