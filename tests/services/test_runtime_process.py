from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Coroutine
from typing import Any

from app.config.settings import SchedulerSettings
from app.runtime.bootstrap import create_memory_runtime_components
from app.runtime.process import RuntimeJobConfig, RuntimeProcess
from app.scheduler.jobs import BaseJob, JobExecutionState


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run async runtime-process checks without an external pytest plugin."""
    return asyncio.run(awaitable)


class CountingJob(BaseJob):
    """Small job double for runtime process tests."""

    def __init__(self) -> None:
        """Initialize the execution counter."""
        super().__init__("counting")
        self.calls = 0

    def run(self) -> object:
        """Record one execution."""
        self.calls += 1
        return None


class SlowJob(BaseJob):
    """Async job double used to verify lifecycle start and stop."""

    def __init__(self) -> None:
        """Initialize execution synchronization."""
        super().__init__("slow")
        self.started = asyncio.Event()
        self.finished = asyncio.Event()

    def run(self) -> Awaitable[object]:
        """Return the controlled async job body."""
        return self._run()

    async def _run(self) -> object:
        self.started.set()
        await self.finished.wait()
        return None


def test_runtime_process_registers_and_executes_existing_job() -> None:
    components = create_memory_runtime_components(
        SchedulerSettings(lease_enabled=False, tick_seconds=0.1),
    )
    process = RuntimeProcess(components)
    job = CountingJob()

    process.register_job(
        job,
        RuntimeJobConfig(retry_count=1, retry_delay_seconds=0.0),
    )
    run_async(process.execute_once(job.name))

    statuses = process.list_statuses()
    statistics = process.list_statistics()

    assert job.calls == 1
    assert statuses[0].state is JobExecutionState.SUCCEEDED
    assert statistics[0].successful_executions == 1


def test_runtime_process_keeps_scheduler_schedule_metadata() -> None:
    process = RuntimeProcess(
        create_memory_runtime_components(
            SchedulerSettings(lease_enabled=False, tick_seconds=0.1),
        ),
    )

    process.register_job(
        CountingJob(),
        RuntimeJobConfig(interval_seconds=30, enabled=False),
    )

    schedule = process.list_schedule_statuses()[0]

    assert schedule.name == "counting"
    assert schedule.interval_seconds == 30
    assert schedule.enabled is False
    assert schedule.next_scheduled_run is None


def test_runtime_process_starts_and_stops_scheduler_lifecycle() -> None:
    process = RuntimeProcess(
        create_memory_runtime_components(
            SchedulerSettings(lease_enabled=False, tick_seconds=0.01),
        ),
    )
    job = SlowJob()
    process.register_job(
        job,
        RuntimeJobConfig(interval_seconds=1, enabled=False),
    )

    async def scenario() -> None:
        process.start()
        await process.stop()

    run_async(scenario())

    assert process.list_statuses()[0].state is JobExecutionState.REGISTERED
