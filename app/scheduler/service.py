from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from importlib import import_module
from inspect import isawaitable
from typing import Any

type SchedulerJob = Callable[[], Awaitable[object] | object]


class JobExecutionState(StrEnum):
    """Possible scheduler job execution states."""

    REGISTERED = "registered"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(slots=True, frozen=True)
class JobExecutionStatus:
    """Last known execution status for a scheduled job."""

    name: str
    state: JobExecutionState
    run_count: int = 0
    failure_count: int = 0
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_error: str | None = None


class SchedulerService:
    """Coordinates scheduled execution of existing application jobs."""

    def __init__(self) -> None:
        """Initialize an empty scheduler service."""
        self._scheduler: Any = self._create_scheduler()
        self._jobs: dict[str, SchedulerJob] = {}
        self._statuses: dict[str, JobExecutionStatus] = {}

    def register_job(
        self,
        name: str,
        job: SchedulerJob,
        *,
        interval_seconds: int | None = None,
    ) -> None:
        """Register a job and optionally schedule periodic execution."""
        self._jobs[name] = job
        self._statuses[name] = JobExecutionStatus(
            name=name,
            state=JobExecutionState.REGISTERED,
        )

        if interval_seconds is not None:
            self._scheduler.add_job(
                self.execute_job,
                trigger="interval",
                seconds=interval_seconds,
                id=name,
                args=(name,),
                replace_existing=True,
            )

    def start(self) -> None:
        """Start the underlying scheduler."""
        if not self._scheduler.running:
            self._scheduler.start()

    def shutdown(self, *, wait: bool = True) -> None:
        """Gracefully stop the underlying scheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=wait)

    async def execute_job(self, name: str) -> None:
        """Execute a registered job and record its status."""
        job = self._jobs[name]
        current_status = self._statuses[name]
        started_at = datetime.now(UTC)
        self._statuses[name] = replace(
            current_status,
            state=JobExecutionState.RUNNING,
            last_started_at=started_at,
            last_finished_at=None,
            last_error=None,
        )

        try:
            result = job()
            if isawaitable(result):
                await result
        except Exception as exc:
            self._statuses[name] = replace(
                self._statuses[name],
                state=JobExecutionState.FAILED,
                run_count=current_status.run_count + 1,
                failure_count=current_status.failure_count + 1,
                last_finished_at=datetime.now(UTC),
                last_error=f"{type(exc).__name__}: {exc}",
            )
            return

        self._statuses[name] = replace(
            self._statuses[name],
            state=JobExecutionState.SUCCEEDED,
            run_count=current_status.run_count + 1,
            last_finished_at=datetime.now(UTC),
            last_error=None,
        )

    def get_status(self, name: str) -> JobExecutionStatus:
        """Return the last known status for a registered job."""
        return self._statuses[name]

    def list_statuses(self) -> tuple[JobExecutionStatus, ...]:
        """Return last known statuses for all registered jobs."""
        return tuple(self._statuses.values())

    @staticmethod
    def _create_scheduler() -> Any:
        """Instantiate the async APScheduler implementation lazily."""
        scheduler_module = import_module("apscheduler.schedulers.asyncio")
        scheduler_class = scheduler_module.AsyncIOScheduler
        return scheduler_class(timezone="UTC")
