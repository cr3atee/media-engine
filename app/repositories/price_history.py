from __future__ import annotations

from abc import abstractmethod
from uuid import UUID

from app.domain.price_snapshot import PriceSnapshot
from app.domain.tenancy import LEGACY_TENANT_ID
from app.repositories.base import BaseRepository


class PriceHistoryRepository(BaseRepository):
    """Abstract storage contract for price snapshot history."""

    @abstractmethod
    async def add(
        self,
        tenant_id: UUID | PriceSnapshot,
        snapshot: PriceSnapshot | None = None,
    ) -> bool:
        """Store a tenant-owned snapshot and return whether it was inserted."""

    @abstractmethod
    async def get_last(
        self,
        tenant_id: UUID | str,
        marketplace: str,
        external_id: str | None = None,
    ) -> PriceSnapshot | None:
        """Return the latest snapshot for one tenant-owned offer identity."""

    @abstractmethod
    async def get_previous(
        self,
        tenant_id: UUID | str,
        marketplace: str,
        external_id: str | None = None,
    ) -> PriceSnapshot | None:
        """Return the snapshot immediately before the latest tenant-owned row."""

    @abstractmethod
    async def get_history(
        self,
        tenant_id: UUID | str,
        marketplace: str,
        external_id: str | None = None,
    ) -> list[PriceSnapshot]:
        """Return tenant-owned snapshots in ascending collection-time order."""


def resolve_snapshot_add_args(
    tenant_id_or_snapshot: UUID | PriceSnapshot,
    snapshot: PriceSnapshot | None,
) -> tuple[UUID, PriceSnapshot]:
    """Resolve explicit tenant-aware and legacy snapshot-add call styles."""
    if isinstance(tenant_id_or_snapshot, PriceSnapshot):
        if snapshot is not None:
            msg = "Snapshot must not be passed twice."
            raise TypeError(msg)
        return tenant_id_or_snapshot.tenant_id, tenant_id_or_snapshot
    if snapshot is None:
        msg = "Snapshot is required when tenant_id is passed explicitly."
        raise TypeError(msg)
    return tenant_id_or_snapshot, snapshot


def resolve_snapshot_identity_args(
    tenant_id_or_marketplace: UUID | str,
    marketplace_or_external_id: str,
    external_id: str | None,
) -> tuple[UUID, str, str]:
    """Resolve explicit tenant-aware and legacy snapshot lookup call styles."""
    if isinstance(tenant_id_or_marketplace, UUID):
        if external_id is None:
            msg = "External ID is required when tenant_id is passed explicitly."
            raise TypeError(msg)
        return tenant_id_or_marketplace, marketplace_or_external_id, external_id
    if external_id is not None:
        msg = "Legacy snapshot lookup accepts only marketplace and external_id."
        raise TypeError(msg)
    return LEGACY_TENANT_ID, tenant_id_or_marketplace, marketplace_or_external_id
