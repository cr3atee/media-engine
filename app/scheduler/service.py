from __future__ import annotations

from importlib import import_module
from typing import Any

from app.scheduler.jobs import BaseJob, JobExecutionStatus


class SchedulerService:
    """Coordinates scheduled execution of existing application jobs."""

    def __init__(self) -> None:
        """Initialize an empty scheduler service."""
        self._scheduler: Any = self._create_scheduler()
        self._jobs: dict[str, BaseJob] = {}
        self._statuses: dict[str, JobExecutionStatus] = {}

    def register_job(
        self,
        job: BaseJob,
        *,
        interval_seconds: int | None = None,
    ) -> None:
        """Register a job and optionally schedule periodic execution."""
        self._jobs[job.name] = job
        self._statuses[job.name] = job.status

        if interval_seconds is not None:
            self._scheduler.add_job(
                self.execute_job,
                trigger="interval",
                seconds=interval_seconds,
                id=job.name,
                args=(job.name,),
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
        await job.execute()
        self._statuses[name] = job.status

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
