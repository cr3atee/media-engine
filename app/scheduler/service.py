from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from importlib import import_module
from typing import Any

from app.scheduler.jobs import BaseJob, JobExecutionState, JobExecutionStatus

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class JobScheduleStatus:
    """Scheduling metadata for a registered job."""

    name: str
    interval_seconds: int | None
    enabled: bool
    next_scheduled_run: datetime | None = None
    last_execution_time: datetime | None = None


@dataclass(slots=True, frozen=True)
class JobRetrySettings:
    """Retry and timeout settings for a registered job."""

    retry_count: int = 0
    retry_delay_seconds: float = 0.0
    timeout_seconds: float | None = None


@dataclass(slots=True, frozen=True)
class JobRuntimeStatistics:
    """Aggregated scheduler statistics for one job."""

    name: str
    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    retry_attempts: int = 0
    last_error: str | None = None
    last_successful_run: datetime | None = None


class SchedulerService:
    """Coordinates scheduled execution of existing application jobs."""

    def __init__(self, *, tick_seconds: float = 0.25) -> None:
        """Initialize an empty scheduler service."""
        self._scheduler: Any = self._create_scheduler()
        self._jobs: dict[str, BaseJob] = {}
        self._statuses: dict[str, JobExecutionStatus] = {}
        self._schedules: dict[str, JobScheduleStatus] = {}
        self._retry_settings: dict[str, JobRetrySettings] = {}
        self._statistics: dict[str, JobRuntimeStatistics] = {}
        self._tick_seconds = tick_seconds
        self._periodic_task: asyncio.Task[None] | None = None

    def register_job(
        self,
        job: BaseJob,
        *,
        interval_seconds: int | None = None,
        enabled: bool = True,
        retry_count: int = 0,
        retry_delay_seconds: float = 0.0,
        timeout_seconds: float | None = None,
    ) -> None:
        """Register a job and optionally schedule periodic execution."""
        if interval_seconds is not None and interval_seconds <= 0:
            msg = "Job interval must be greater than zero seconds."
            raise ValueError(msg)
        if retry_count < 0:
            msg = "Retry count must be greater than or equal to zero."
            raise ValueError(msg)
        if retry_delay_seconds < 0:
            msg = "Retry delay must be greater than or equal to zero."
            raise ValueError(msg)
        if timeout_seconds is not None and timeout_seconds <= 0:
            msg = "Timeout must be greater than zero seconds."
            raise ValueError(msg)

        self._jobs[job.name] = job
        self._statuses[job.name] = job.status
        self._schedules[job.name] = JobScheduleStatus(
            name=job.name,
            interval_seconds=interval_seconds,
            enabled=enabled,
            next_scheduled_run=self._next_run(interval_seconds, enabled),
        )
        self._retry_settings[job.name] = JobRetrySettings(
            retry_count=retry_count,
            retry_delay_seconds=retry_delay_seconds,
            timeout_seconds=timeout_seconds,
        )
        self._statistics[job.name] = JobRuntimeStatistics(name=job.name)

    def start(self) -> None:
        """Start the underlying scheduler."""
        if not self._scheduler.running:
            self._scheduler.start()
        if self._periodic_task is None or self._periodic_task.done():
            self._periodic_task = asyncio.create_task(self._run_periodic_loop())

    def shutdown(self, *, wait: bool = True) -> None:
        """Gracefully stop the underlying scheduler."""
        logger.info("STOP", extra={"component": "scheduler"})
        if self._periodic_task is not None:
            self._periodic_task.cancel()
        if self._scheduler.running:
            self._scheduler.shutdown(wait=wait)

    async def stop(self) -> None:
        """Cancel periodic execution and stop the scheduler cleanly."""
        logger.info("STOP", extra={"component": "scheduler"})
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
        settings = self._retry_settings[name]
        max_attempts = settings.retry_count + 1

        for attempt in range(1, max_attempts + 1):
            logger.info(
                "START",
                extra={"job": name, "attempt": attempt, "max_attempts": max_attempts},
            )
            timed_out = await self._execute_once(name, job, settings)
            status = self._statuses[name]
            if status.state is JobExecutionState.SUCCEEDED:
                self._record_success(name)
                logger.info("SUCCESS", extra={"job": name, "attempt": attempt})
                break

            if timed_out:
                logger.info("TIMEOUT", extra={"job": name, "attempt": attempt})
            else:
                logger.info(
                    "FAILURE",
                    extra={"job": name, "attempt": attempt, "error": status.last_error},
                )

            if attempt < max_attempts:
                self._record_retry(name)
                logger.info(
                    "RETRY",
                    extra={"job": name, "next_attempt": attempt + 1},
                )
                if settings.retry_delay_seconds > 0:
                    await asyncio.sleep(settings.retry_delay_seconds)
                continue

            self._record_failure(name)

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

    def get_statistics(self, name: str) -> JobRuntimeStatistics:
        """Return aggregated scheduler statistics for a registered job."""
        return self._statistics[name]

    def list_statistics(self) -> tuple[JobRuntimeStatistics, ...]:
        """Return aggregated scheduler statistics for all registered jobs."""
        return tuple(self._statistics.values())

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

    async def _execute_once(
        self,
        name: str,
        job: BaseJob,
        settings: JobRetrySettings,
    ) -> bool:
        try:
            if settings.timeout_seconds is None:
                await job.execute()
            else:
                await asyncio.wait_for(
                    job.execute(),
                    timeout=settings.timeout_seconds,
                )
        except TimeoutError:
            self._statuses[name] = replace(
                job.status,
                state=JobExecutionState.FAILED,
                last_finished_at=datetime.now(UTC),
                last_error="TimeoutError: job execution timed out",
            )
            return True

        self._statuses[name] = job.status
        return False

    def _record_retry(self, name: str) -> None:
        statistics = self._statistics[name]
        self._statistics[name] = replace(
            statistics,
            retry_attempts=statistics.retry_attempts + 1,
            last_error=self._statuses[name].last_error,
        )

    def _record_success(self, name: str) -> None:
        statistics = self._statistics[name]
        self._statistics[name] = replace(
            statistics,
            total_executions=statistics.total_executions + 1,
            successful_executions=statistics.successful_executions + 1,
            last_error=None,
            last_successful_run=self._statuses[name].last_finished_at,
        )

    def _record_failure(self, name: str) -> None:
        statistics = self._statistics[name]
        self._statistics[name] = replace(
            statistics,
            total_executions=statistics.total_executions + 1,
            failed_executions=statistics.failed_executions + 1,
            last_error=self._statuses[name].last_error,
        )

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
