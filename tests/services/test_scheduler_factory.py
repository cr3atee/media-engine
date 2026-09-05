from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Coroutine
from typing import Any

import pytest

from app.config.settings import SchedulerSettings
from app.repositories.memory import MemorySchedulerLeaseRepository
from app.scheduler.factory import (
    create_memory_scheduler_service,
    create_scheduler_service,
)
from app.scheduler.jobs import BaseJob, JobExecutionState


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run async scheduler checks without requiring a pytest plugin."""
    return asyncio.run(awaitable)


class CountingJob(BaseJob):
    """Minimal job double for scheduler factory tests."""

    def __init__(self) -> None:
        """Initialize execution counters."""
        super().__init__("counting")
        self.calls = 0

    def run(self) -> object:
        """Record one execution."""
        self.calls += 1
        return None


class ControlledJob(BaseJob):
    """Job double that keeps the scheduler lease active during the test."""

    def __init__(self) -> None:
        """Initialize execution counters and synchronization events."""
        super().__init__("counting")
        self.calls = 0
        self.started = asyncio.Event()
        self.finished = asyncio.Event()

    def run(self) -> Awaitable[object]:
        """Return the controlled async execution body."""
        return self._run()

    async def _run(self) -> object:
        self.calls += 1
        self.started.set()
        await self.finished.wait()
        return None


def test_scheduler_factory_requires_repository_when_leases_are_enabled() -> None:
    scheduler_settings = SchedulerSettings(lease_enabled=True)

    with pytest.raises(ValueError, match="no lease repository"):
        create_scheduler_service(scheduler_settings)


def test_scheduler_factory_runs_without_lease_when_disabled() -> None:
    scheduler_settings = SchedulerSettings(lease_enabled=False, tick_seconds=0.1)
    scheduler = create_scheduler_service(scheduler_settings)
    job = CountingJob()
    scheduler.register_job(job)

    run_async(scheduler.execute_job("counting"))

    assert job.calls == 1
    assert scheduler.get_status("counting").state is JobExecutionState.SUCCEEDED


def test_scheduler_factory_uses_configured_lease_repository() -> None:
    lease_repository = MemorySchedulerLeaseRepository()
    first = create_scheduler_service(
        SchedulerSettings(
            lease_enabled=True,
            owner_id="node-a",
            lease_ttl_seconds=30,
        ),
        lease_repository=lease_repository,
    )
    second = create_scheduler_service(
        SchedulerSettings(
            lease_enabled=True,
            owner_id="node-b",
            lease_ttl_seconds=30,
        ),
        lease_repository=lease_repository,
    )
    first_job = ControlledJob()
    second_job = CountingJob()
    first.register_job(first_job)
    second.register_job(second_job)

    async def scenario() -> None:
        running = asyncio.create_task(first.execute_job("counting"))
        await first_job.started.wait()
        await second.execute_job("counting")
        first_job.finished.set()
        await running

    run_async(scenario())

    assert second_job.calls == 0
    assert second.get_statistics("counting").lease_skips == 1
    assert first_job.calls == 1


def test_memory_scheduler_factory_respects_disabled_lease_setting() -> None:
    scheduler = create_memory_scheduler_service(SchedulerSettings(lease_enabled=False))
    job = CountingJob()
    scheduler.register_job(job)

    run_async(scheduler.execute_job("counting"))

    assert job.calls == 1
