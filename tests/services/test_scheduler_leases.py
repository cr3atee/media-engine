from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import Table

from app.domain.scheduler_leases import SchedulerLease
from app.models.scheduler_lease_record import SchedulerLeaseRecord
from app.repositories.memory import MemorySchedulerLeaseRepository
from app.scheduler.jobs import BaseJob, JobExecutionState
from app.scheduler.service import SchedulerService

NOW = datetime(2026, 9, 4, 9, 0, tzinfo=UTC)


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run async scheduler checks without requiring a pytest plugin."""
    return asyncio.run(awaitable)


class ControlledJob(BaseJob):
    """Job double that remains running until the test releases it."""

    def __init__(self, name: str) -> None:
        """Initialize execution counters and synchronization events."""
        super().__init__(name)
        self.started = asyncio.Event()
        self.finished = asyncio.Event()
        self.run_count = 0

    def run(self) -> Awaitable[object]:
        """Return the controlled async execution body."""
        return self._run()

    async def _run(self) -> object:
        self.run_count += 1
        self.started.set()
        await self.finished.wait()
        return None


def test_scheduler_lease_validates_and_reports_active_state() -> None:
    lease = SchedulerLease(
        job_name=" marketplace-sync ",
        owner_id=" node-a ",
        acquired_at=NOW,
        expires_at=NOW + timedelta(seconds=30),
    )

    assert lease.job_name == "marketplace-sync"
    assert lease.owner_id == "node-a"
    assert lease.is_active_at(NOW + timedelta(seconds=29)) is True
    assert lease.is_active_at(NOW + timedelta(seconds=30)) is False


def test_memory_scheduler_lease_acquires_releases_and_recovers_expired() -> None:
    repository = MemorySchedulerLeaseRepository()

    async def scenario() -> None:
        first = await repository.acquire(
            job_name="marketplace-sync",
            owner_id="node-a",
            acquired_at=NOW,
            expires_at=NOW + timedelta(seconds=30),
        )
        blocked = await repository.acquire(
            job_name="marketplace-sync",
            owner_id="node-b",
            acquired_at=NOW + timedelta(seconds=1),
            expires_at=NOW + timedelta(seconds=31),
        )
        wrong_release = await repository.release(
            job_name="marketplace-sync",
            owner_id="node-b",
        )
        released = await repository.release(
            job_name="marketplace-sync",
            owner_id="node-a",
        )
        recovered = await repository.acquire(
            job_name="marketplace-sync",
            owner_id="node-c",
            acquired_at=NOW + timedelta(seconds=31),
            expires_at=NOW + timedelta(seconds=61),
        )

        assert first is True
        assert blocked is False
        assert wrong_release is False
        assert released is True
        assert recovered is True

    run_async(scenario())


def test_scheduler_service_skips_job_when_active_lease_exists() -> None:
    repository = MemorySchedulerLeaseRepository()

    async def scenario() -> None:
        first_job = ControlledJob("marketplace-sync")
        second_job = ControlledJob("marketplace-sync")
        first = SchedulerService(
            lease_repository=repository,
            owner_id="node-a",
            lease_ttl_seconds=30,
        )
        second = SchedulerService(
            lease_repository=repository,
            owner_id="node-b",
            lease_ttl_seconds=30,
        )
        first.register_job(first_job)
        second.register_job(second_job)

        running = asyncio.create_task(first.execute_job("marketplace-sync"))
        await first_job.started.wait()
        await second.execute_job("marketplace-sync")
        first_job.finished.set()
        await running

        assert first_job.run_count == 1
        assert second_job.run_count == 0
        assert first.get_status("marketplace-sync").state is JobExecutionState.SUCCEEDED
        assert second.get_statistics("marketplace-sync").lease_skips == 1
        assert await repository.get("marketplace-sync") is None

    run_async(scenario())


def test_scheduler_lease_metadata_matches_persistence_contract() -> None:
    table = cast(Table, SchedulerLeaseRecord.__table__)
    constraints = {constraint.name for constraint in table.constraints}
    indexes = {str(index.name): index for index in table.indexes}

    assert "pk_scheduler_leases" in constraints
    assert "ck_scheduler_leases_job_name_nonempty" in constraints
    assert "ck_scheduler_leases_owner_id_nonempty" in constraints
    assert "ck_scheduler_leases_expiry_after_acquisition" in constraints
    assert tuple(
        column.name for column in indexes["ix_scheduler_leases_expires_at"].columns
    ) == ("expires_at",)
