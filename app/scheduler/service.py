from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from importlib import import_module
from typing import Any

from app.scheduler.jobs import BaseJob, JobExecutionStatus


@dataclass(slots=True, frozen=True)
class JobScheduleStatus:
    """Scheduling metadata for a registered job."""

    name: str
    interval_seconds: int | None
    enabled: bool
    next_scheduled_run: datetime | None = None
    last_execution_time: datetime | None = None


class SchedulerService:
    """Coordinates scheduled execution of existing application jobs."""

    def __init__(self, *, tick_seconds: float = 0.25) -> None:
        """Initialize an empty scheduler service."""
        self._scheduler: Any = self._create_scheduler()
        self._jobs: dict[str, BaseJob] = {}
        self._statuses: dict[str, JobExecutionStatus] = {}
        self._schedules: dict[str, JobScheduleStatus] = {}
        self._tick_seconds = tick_seconds
        self._periodic_task: asyncio.Task[None] | None = None

    def register_job(
        self,
        job: BaseJob,
        *,
        interval_seconds: int | None = None,
        enabled: bool = True,
    ) -> None:
        """Register a job and optionally schedule periodic execution."""
        if interval_seconds is not None and interval_seconds <= 0:
            msg = "Job interval must be greater than zero seconds."
            raise ValueError(msg)

        self._jobs[job.name] = job
        self._statuses[job.name] = job.status
        self._schedules[job.name] = JobScheduleStatus(
            name=job.name,
            interval_seconds=interval_seconds,
            enabled=enabled,
            next_scheduled_run=self._next_run(interval_seconds, enabled),
        )

    def start(self) -> None:
        """Start the underlying scheduler."""
        if not self._scheduler.running:
            self._scheduler.start()
        if self._periodic_task is None or self._periodic_task.done():
            self._periodic_task = asyncio.create_task(self._run_periodic_loop())

    def shutdown(self, *, wait: bool = True) -> None:
        """Gracefully stop the underlying scheduler."""
        if self._periodic_task is not None:
            self._periodic_task.cancel()
        if self._scheduler.running:
            self._scheduler.shutdown(wait=wait)

    async def stop(self) -> None:
        """Cancel periodic execution and stop the scheduler cleanly."""
        if self._periodic_task is not None:
            self._periodic_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._periodic_task
            self._periodic_task = None

        if self._scheduler.running:
            self._scheduler.shutdown(wait=True)

    async def execute_job(self, name: str) -> None:
        """Execute a registered job and record its status."""
        job = self._jobs[name]
        await job.execute()
        self._statuses[name] = job.status
        self._refresh_schedule_after_execution(name)

    def enable_job(self, name: str) -> None:
        """Enable periodic execution for a registered job."""
        schedule = self._schedules[name]
        self._schedules[name] = replace(
            schedule,
            enabled=True,
            next_scheduled_run=self._next_run(schedule.interval_seconds, True),
        )

    def disable_job(self, name: str) -> None:
        """Disable periodic execution for a registered job."""
        self._schedules[name] = replace(
            self._schedules[name],
            enabled=False,
            next_scheduled_run=None,
        )

    def get_schedule_status(self, name: str) -> JobScheduleStatus:
        """Return scheduling metadata for a registered job."""
        return self._schedules[name]

    def list_schedule_statuses(self) -> tuple[JobScheduleStatus, ...]:
        """Return scheduling metadata for all registered jobs."""
        return tuple(self._schedules.values())

    def get_status(self, name: str) -> JobExecutionStatus:
        """Return the last known status for a registered job."""
        return self._statuses[name]

    def list_statuses(self) -> tuple[JobExecutionStatus, ...]:
        """Return last known statuses for all registered jobs."""
        return tuple(self._statuses.values())

    async def _run_periodic_loop(self) -> None:
        while True:
            await self._execute_due_jobs()
            await asyncio.sleep(self._tick_seconds)

    async def _execute_due_jobs(self) -> None:
        now = datetime.now(UTC)
        due_jobs = [
            schedule.name
            for schedule in self._schedules.values()
            if (
                schedule.enabled
                and schedule.interval_seconds is not None
                and schedule.next_scheduled_run is not None
                and schedule.next_scheduled_run <= now
            )
        ]

        for name in due_jobs:
            await self.execute_job(name)

    def _refresh_schedule_after_execution(self, name: str) -> None:
        schedule = self._schedules.get(name)
        if schedule is None:
            return

        finished_at = self._statuses[name].last_finished_at
        self._schedules[name] = replace(
            schedule,
            last_execution_time=finished_at,
            next_scheduled_run=self._next_run(
                schedule.interval_seconds,
                schedule.enabled,
            ),
        )

    def _next_run(
        self,
        interval_seconds: int | None,
        enabled: bool,
    ) -> datetime | None:
        if not enabled or interval_seconds is None:
            return None
        return datetime.now(UTC) + timedelta(seconds=interval_seconds)

    @staticmethod
    def _create_scheduler() -> Any:
        """Instantiate the async APScheduler implementation lazily."""
        scheduler_module = import_module("apscheduler.schedulers.asyncio")
        scheduler_class = scheduler_module.AsyncIOScheduler
        return scheduler_class(timezone="UTC")
