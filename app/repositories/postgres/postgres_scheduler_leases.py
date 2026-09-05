from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.scheduler_leases import SchedulerLease
from app.models.scheduler_lease_record import SchedulerLeaseRecord
from app.repositories.scheduler_leases import SchedulerLeaseRepository


class PostgresSchedulerLeaseRepository(SchedulerLeaseRepository):
    """PostgreSQL scheduler lease repository with short atomic transactions."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Bind the repository to a session factory for isolated lease writes."""
        self._session_factory = session_factory

    async def acquire(
        self,
        *,
        job_name: str,
        owner_id: str,
        acquired_at: datetime,
        expires_at: datetime,
    ) -> bool:
        """Atomically acquire a lease unless another active owner holds it."""
        lease = SchedulerLease(
            job_name=job_name,
            owner_id=owner_id,
            acquired_at=acquired_at,
            expires_at=expires_at,
        )
        statement = (
            insert(SchedulerLeaseRecord)
            .values(
                job_name=lease.job_name,
                owner_id=lease.owner_id,
                acquired_at=lease.acquired_at,
                expires_at=lease.expires_at,
            )
            .on_conflict_do_update(
                index_elements=[SchedulerLeaseRecord.job_name],
                set_={
                    "owner_id": lease.owner_id,
                    "acquired_at": lease.acquired_at,
                    "expires_at": lease.expires_at,
                },
                where=SchedulerLeaseRecord.expires_at <= lease.acquired_at,
            )
            .returning(SchedulerLeaseRecord.job_name)
        )

        async with self._session_factory() as session, session.begin():
            result = await session.execute(statement)
            return result.scalar_one_or_none() is not None

    async def release(self, *, job_name: str, owner_id: str) -> bool:
        """Release the current lease only when owned by the caller."""
        statement = (
            delete(SchedulerLeaseRecord)
            .where(
                SchedulerLeaseRecord.job_name == job_name,
                SchedulerLeaseRecord.owner_id == owner_id,
            )
            .returning(SchedulerLeaseRecord.job_name)
        )
        async with self._session_factory() as session, session.begin():
            result = await session.execute(statement)
            return result.scalar_one_or_none() is not None

    async def get(self, job_name: str) -> SchedulerLease | None:
        """Return the stored lease for one scheduler job."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(SchedulerLeaseRecord).where(
                    SchedulerLeaseRecord.job_name == job_name,
                )
            )
            record = result.scalar_one_or_none()
            if record is None:
                return None
            return SchedulerLease(
                job_name=record.job_name,
                owner_id=record.owner_id,
                acquired_at=record.acquired_at,
                expires_at=record.expires_at,
            )
