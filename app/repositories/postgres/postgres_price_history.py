from __future__ import annotations

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.price_snapshot import PriceSnapshot
from app.domain.tenancy import LEGACY_TENANT_ID
from app.models.price_snapshot_record import PriceSnapshotRecord
from app.repositories.price_history import PriceHistoryRepository


class PostgresPriceHistoryRepository(PriceHistoryRepository):
    """PostgreSQL-backed repository for marketplace price snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with an existing async database session."""
        self._session = session

    async def add(self, snapshot: PriceSnapshot) -> bool:
        """Insert a snapshot and report whether PostgreSQL created a row."""
        statement = (
            insert(PriceSnapshotRecord)
            .values(
                tenant_id=snapshot.tenant_id,
                marketplace=snapshot.marketplace,
                external_id=snapshot.external_id,
                price=snapshot.price,
                currency=snapshot.currency,
                collected_at=snapshot.collected_at,
            )
            .on_conflict_do_nothing(
                constraint="uq_price_snapshots_exact_identity",
            )
            .returning(PriceSnapshotRecord.id)
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none() is not None

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
        result = await self._session.execute(
            self._base_query(tenant_id, marketplace, external_id)
            .order_by(
                PriceSnapshotRecord.collected_at.desc(),
                PriceSnapshotRecord.id.desc(),
            )
            .limit(1)
        )
        record = result.scalar_one_or_none()
        return self._to_domain(record) if record is not None else None

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
        result = await self._session.execute(
            self._base_query(tenant_id, marketplace, external_id)
            .order_by(
                PriceSnapshotRecord.collected_at.desc(),
                PriceSnapshotRecord.id.desc(),
            )
            .offset(1)
            .limit(1)
        )
        record = result.scalar_one_or_none()
        return self._to_domain(record) if record is not None else None

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
        """Return tenant snapshots by collection time, then record ID."""
        result = await self._session.execute(
            self._base_query(tenant_id, marketplace, external_id).order_by(
                PriceSnapshotRecord.collected_at,
                PriceSnapshotRecord.id,
            )
        )
        return [self._to_domain(record) for record in result.scalars()]

    @staticmethod
    def _base_query(
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
    ) -> Select[tuple[PriceSnapshotRecord]]:
        return select(PriceSnapshotRecord).where(
            PriceSnapshotRecord.tenant_id == tenant_id,
            PriceSnapshotRecord.marketplace == marketplace,
            PriceSnapshotRecord.external_id == external_id,
        )

    @staticmethod
    def _to_domain(record: PriceSnapshotRecord) -> PriceSnapshot:
        return PriceSnapshot(
            tenant_id=record.tenant_id,
            marketplace=record.marketplace,
            external_id=record.external_id,
            price=record.price,
            currency=record.currency,
            collected_at=record.collected_at,
        )
