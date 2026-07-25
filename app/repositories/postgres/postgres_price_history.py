from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.price_snapshot import PriceSnapshot
from app.models.price_snapshot_record import PriceSnapshotRecord
from app.repositories.price_history import PriceHistoryRepository


class PostgresPriceHistoryRepository(PriceHistoryRepository):
    """PostgreSQL-backed repository for marketplace price snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with an existing async database session."""
        self._session = session

    async def add(self, snapshot: PriceSnapshot) -> None:  # type: ignore[override]
        """Store a price snapshot in insertion order."""
        self._session.add(
            PriceSnapshotRecord(
                marketplace=snapshot.marketplace,
                external_id=snapshot.external_id,
                price=snapshot.price,
                currency=snapshot.currency,
                collected_at=snapshot.collected_at,
            )
        )
        await self._session.flush()

    async def get_last(  # type: ignore[override]
        self,
        marketplace: str,
        external_id: str,
    ) -> PriceSnapshot | None:
        """Return the latest stored snapshot for a marketplace offer."""
        result = await self._session.execute(
            self._base_query(marketplace, external_id)
            .order_by(PriceSnapshotRecord.id.desc())
            .limit(1)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return self._to_domain(record)

    async def get_previous(  # type: ignore[override]
        self,
        marketplace: str,
        external_id: str,
    ) -> PriceSnapshot | None:
        """Return the snapshot before the latest one for a marketplace offer."""
        result = await self._session.execute(
            self._base_query(marketplace, external_id)
            .order_by(PriceSnapshotRecord.id.desc())
            .offset(1)
            .limit(1)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return self._to_domain(record)

    async def get_history(  # type: ignore[override]
        self,
        marketplace: str,
        external_id: str,
    ) -> list[PriceSnapshot]:
        """Return all stored snapshots for a marketplace offer."""
        result = await self._session.execute(
            self._base_query(marketplace, external_id).order_by(PriceSnapshotRecord.id)
        )
        return [self._to_domain(record) for record in result.scalars()]

    @staticmethod
    def _base_query(
        marketplace: str,
        external_id: str,
    ) -> Select[tuple[PriceSnapshotRecord]]:
        return select(PriceSnapshotRecord).where(
            PriceSnapshotRecord.marketplace == marketplace,
            PriceSnapshotRecord.external_id == external_id,
        )

    @staticmethod
    def _to_domain(record: PriceSnapshotRecord) -> PriceSnapshot:
        return PriceSnapshot(
            marketplace=record.marketplace,
            external_id=record.external_id,
            price=record.price,
            currency=record.currency,
            collected_at=record.collected_at,
        )
