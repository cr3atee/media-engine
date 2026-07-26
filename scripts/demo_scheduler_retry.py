# ruff: noqa: E402

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Awaitable
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.scheduler import BaseJob, SchedulerService


class SuccessfulJob(BaseJob):  # type: ignore[misc]
    """Demo job that always succeeds."""

    def __init__(self) -> None:
        """Initialize the successful demo job."""
        super().__init__("successful-job")

    def run(self) -> Awaitable[object]:
        """Execute a successful async operation."""
        return self._run()

    async def _run(self) -> object:
        await asyncio.sleep(0.01)
        return None


class FailingJob(BaseJob):  # type: ignore[misc]
    """Demo job that fails intentionally."""

    def __init__(self) -> None:
        """Initialize the failing demo job."""
        super().__init__("failing-job")

    def run(self) -> Awaitable[object]:
        """Execute an intentionally failing async operation."""
        return self._run()

    async def _run(self) -> object:
        await asyncio.sleep(0.01)
        msg = "intentional scheduler demo failure"
        raise RuntimeError(msg)


async def main() -> None:
    """Demonstrate scheduler retry and failure handling."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    scheduler = SchedulerService()
    scheduler.start()

    scheduler.register_job(
        SuccessfulJob(),
        retry_count=2,
        retry_delay_seconds=0.05,
        timeout_seconds=1.0,
    )
    scheduler.register_job(
        FailingJob(),
        retry_count=2,
        retry_delay_seconds=0.05,
        timeout_seconds=1.0,
    )

    print("Execute successful job")
    await scheduler.execute_job("successful-job")

    print("Execute failing job with retries")
    await scheduler.execute_job("failing-job")

    print("Scheduler continues running")
    for status in scheduler.list_statuses():
        statistics = scheduler.get_statistics(status.name)
        print(f"Job: {status.name}")
        print(f"Status: {status.state.value}")
        print(f"Total executions: {statistics.total_executions}")
        print(f"Successful executions: {statistics.successful_executions}")
        print(f"Failed executions: {statistics.failed_executions}")
        print(f"Retry attempts: {statistics.retry_attempts}")
        print(f"Last error: {statistics.last_error}")
        print(f"Last successful run: {statistics.last_successful_run}")

    await scheduler.stop()


if __name__ == "__main__":
    asyncio.run(main())
