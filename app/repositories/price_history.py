from __future__ import annotations

from abc import abstractmethod
from uuid import UUID

from app.domain.price_snapshot import PriceSnapshot
from app.domain.tenancy import LEGACY_TENANT_ID
from app.repositories.base import BaseRepository, RepositoryIdentityConflictError


class PriceHistoryRepository(BaseRepository):
    """Abstract storage contract for price snapshot history."""

    @abstractmethod
    async def add(self, snapshot: PriceSnapshot) -> bool:
        """Store a snapshot using its durable tenant ownership."""

    @abstractmethod
    async def get_last(
        self,
        marketplace: str,
        external_id: str,
    ) -> PriceSnapshot | None:
        """Return the latest legacy-tenant snapshot for an offer."""

    @abstractmethod
    async def get_previous(
        self,
        marketplace: str,
        external_id: str,
    ) -> PriceSnapshot | None:
        """Return the previous legacy-tenant snapshot for an offer."""

    @abstractmethod
    async def get_history(
        self,
        marketplace: str,
        external_id: str,
    ) -> list[PriceSnapshot]:
        """Return legacy-tenant snapshots in chronological order."""

    async def add_for_tenant(
        self,
        tenant_id: UUID,
        snapshot: PriceSnapshot,
    ) -> bool:
        """Store a snapshot after validating its explicit tenant context."""
        _validate_tenant(tenant_id, snapshot.tenant_id)
        return await self.add(snapshot)

    async def get_last_for_tenant(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
    ) -> PriceSnapshot | None:
        """Return the latest snapshot for one tenant-owned offer identity."""
        if tenant_id == LEGACY_TENANT_ID:
            return await self.get_last(marketplace, external_id)
        history = await self.get_history_for_tenant(
            tenant_id,
            marketplace,
            external_id,
        )
        return history[-1] if history else None

    async def get_previous_for_tenant(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
    ) -> PriceSnapshot | None:
        """Return the snapshot immediately before the latest tenant row."""
        if tenant_id == LEGACY_TENANT_ID:
            return await self.get_previous(marketplace, external_id)
        history = await self.get_history_for_tenant(
            tenant_id,
            marketplace,
            external_id,
        )
        return history[-2] if len(history) >= 2 else None

    async def get_history_for_tenant(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
    ) -> list[PriceSnapshot]:
        """Return tenant-owned snapshots in chronological order."""
        if tenant_id == LEGACY_TENANT_ID:
            return await self.get_history(marketplace, external_id)
        msg = (
            f"{type(self).__name__} does not implement non-legacy tenant price history."
        )
        raise NotImplementedError(msg)


def _validate_tenant(requested: UUID, actual: UUID) -> None:
    if requested != actual:
        msg = f"Snapshot tenant mismatch: requested {requested}, got {actual}."
        raise RepositoryIdentityConflictError(msg)
