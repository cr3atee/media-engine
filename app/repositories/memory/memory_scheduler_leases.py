from __future__ import annotations

from datetime import datetime

from app.domain.scheduler_leases import SchedulerLease
from app.repositories.scheduler_leases import SchedulerLeaseRepository


class MemorySchedulerLeaseRepository(SchedulerLeaseRepository):
    """In-memory scheduler lease repository for demos and local tests."""

    def __init__(self) -> None:
        """Initialize empty lease storage."""
        self._leases: dict[str, SchedulerLease] = {}

    async def acquire(
        self,
        *,
        job_name: str,
        owner_id: str,
        acquired_at: datetime,
        expires_at: datetime,
    ) -> bool:
        """Acquire a job lease when the existing lease is missing or expired."""
        lease = SchedulerLease(
            job_name=job_name,
            owner_id=owner_id,
            acquired_at=acquired_at,
            expires_at=expires_at,
        )
        current = self._leases.get(lease.job_name)
        if current is not None and current.is_active_at(lease.acquired_at):
            return False

        self._leases[lease.job_name] = lease
        return True

    async def release(self, *, job_name: str, owner_id: str) -> bool:
        """Release a lease only when the caller owns the stored lease."""
        current = self._leases.get(job_name)
        if current is None or current.owner_id != owner_id:
            return False

        del self._leases[job_name]
        return True

    async def get(self, job_name: str) -> SchedulerLease | None:
        """Return the stored lease for one job, if present."""
        return self._leases.get(job_name)
