from __future__ import annotations

from abc import abstractmethod
from datetime import datetime

from app.domain.scheduler_leases import SchedulerLease
from app.repositories.base import BaseRepository


class SchedulerLeaseRepository(BaseRepository):
    """Abstract storage contract for scheduler job execution leases."""

    @abstractmethod
    async def acquire(
        self,
        *,
        job_name: str,
        owner_id: str,
        acquired_at: datetime,
        expires_at: datetime,
    ) -> bool:
        """Acquire a lease when no active owner currently holds the job slot."""

    @abstractmethod
    async def release(self, *, job_name: str, owner_id: str) -> bool:
        """Release a lease only when it is owned by the provided owner."""

    @abstractmethod
    async def get(self, job_name: str) -> SchedulerLease | None:
        """Return the current lease for a job, if one is stored."""
