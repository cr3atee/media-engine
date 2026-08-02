from __future__ import annotations

from uuid import UUID

from app.domain.price_snapshot import PriceSnapshot
from app.domain.tenancy import LEGACY_TENANT_ID
from app.repositories.price_history import PriceHistoryRepository


class MemoryPriceHistoryRepository(PriceHistoryRepository):
    """In-memory repository for marketplace price snapshots."""

    def __init__(self) -> None:
        """Initialize empty price history storage."""
        self._storage: dict[tuple[UUID, str, str], list[PriceSnapshot]] = {}

    async def add(self, snapshot: PriceSnapshot) -> bool:
        """Store a snapshot and report whether it was newly inserted."""
        key = (snapshot.tenant_id, snapshot.marketplace, snapshot.external_id)
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
        """Return the latest legacy-tenant snapshot for an offer."""
        return await self.get_last_for_tenant(
            LEGACY_TENANT_ID,
            marketplace,
            external_id,
        )

    async def get_last_for_tenant(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
    ) -> PriceSnapshot | None:
        """Return the latest stored snapshot for a tenant-owned offer."""
        history = await self.get_history_for_tenant(
            tenant_id,
            marketplace,
            external_id,
        )
        return history[-1] if history else None

    async def get_previous(
        self,
        marketplace: str,
        external_id: str,
    ) -> PriceSnapshot | None:
        """Return the previous legacy-tenant snapshot for an offer."""
        return await self.get_previous_for_tenant(
            LEGACY_TENANT_ID,
            marketplace,
            external_id,
        )

    async def get_previous_for_tenant(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
    ) -> PriceSnapshot | None:
        """Return the snapshot before the latest tenant-owned row."""
        history = await self.get_history_for_tenant(
            tenant_id,
            marketplace,
            external_id,
        )
        return history[-2] if len(history) >= 2 else None

    async def get_history(
        self,
        marketplace: str,
        external_id: str,
    ) -> list[PriceSnapshot]:
        """Return legacy-tenant snapshots in chronological order."""
        return await self.get_history_for_tenant(
            LEGACY_TENANT_ID,
            marketplace,
            external_id,
        )

    async def get_history_for_tenant(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
    ) -> list[PriceSnapshot]:
        """Return tenant snapshots by collection time, then insertion order."""
        history = self._storage.get((tenant_id, marketplace, external_id), [])
        ordered = sorted(
            enumerate(history),
            key=lambda item: (item[1].collected_at, item[0]),
        )
        return [snapshot for _, snapshot in ordered]
