from __future__ import annotations

from dataclasses import dataclass

from app.runtime.bootstrap import RuntimeComponents
from app.scheduler.jobs import BaseJob, JobExecutionStatus
from app.scheduler.service import (
    JobRuntimeStatistics,
    JobScheduleStatus,
)


@dataclass(slots=True, frozen=True)
class RuntimeJobConfig:
    """Scheduler registration settings used by runtime process entrypoints."""

    interval_seconds: int | None = None
    enabled: bool = True
    retry_count: int = 0
    retry_delay_seconds: float = 0.0
    timeout_seconds: float | None = None


class RuntimeProcess:
    """Thin lifecycle boundary around configured runtime components."""

    def __init__(self, components: RuntimeComponents) -> None:
        """Initialize the process with prebuilt runtime components."""
        self._components = components

    @property
    def components(self) -> RuntimeComponents:
        """Return the process runtime components."""
        return self._components

    def register_job(
        self,
        job: BaseJob,
        config: RuntimeJobConfig | None = None,
    ) -> None:
        """Register an existing Scheduler job without owning its work."""
        job_config = config or RuntimeJobConfig()
        self._components.scheduler.register_job(
            job,
            interval_seconds=job_config.interval_seconds,
            enabled=job_config.enabled,
            retry_count=job_config.retry_count,
            retry_delay_seconds=job_config.retry_delay_seconds,
            timeout_seconds=job_config.timeout_seconds,
        )

    async def execute_once(self, job_name: str) -> None:
        """Execute one registered job through the configured Scheduler."""
        await self._components.scheduler.execute_job(job_name)

    def start(self) -> None:
        """Start periodic execution through the configured Scheduler."""
        self._components.scheduler.start()

    async def stop(self) -> None:
        """Stop periodic execution and release Scheduler resources."""
        await self._components.scheduler.stop()

    def list_statuses(self) -> tuple[JobExecutionStatus, ...]:
        """Return execution statuses for all registered jobs."""
        return self._components.scheduler.list_statuses()

    def list_schedule_statuses(self) -> tuple[JobScheduleStatus, ...]:
        """Return schedule metadata for all registered jobs."""
        return self._components.scheduler.list_schedule_statuses()

    def list_statistics(self) -> tuple[JobRuntimeStatistics, ...]:
        """Return runtime statistics for all registered jobs."""
        return self._components.scheduler.list_statistics()
