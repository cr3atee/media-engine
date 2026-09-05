"""Demonstrate Scheduler lease coordination."""

# ruff: noqa: E402
from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.repositories.memory import MemorySchedulerLeaseRepository
from app.scheduler.jobs import BaseJob
from app.scheduler.service import SchedulerService


class DemoJob(BaseJob):
    """Small job used to demonstrate scheduler lease coordination."""

    def __init__(self, name: str) -> None:
        """Initialize the job synchronization state."""
        super().__init__(name)
        self.started = asyncio.Event()
        self.finish = asyncio.Event()

    def run(self) -> Awaitable[object]:
        """Run until the demo releases the job."""
        return self._run()

    async def _run(self) -> object:
        self.started.set()
        await self.finish.wait()
        return None


async def main() -> None:
    """Run two scheduler instances against one shared lease repository."""
    leases = MemorySchedulerLeaseRepository()
    first_job = DemoJob("marketplace-sync")
    second_job = DemoJob("marketplace-sync")
    first_scheduler = SchedulerService(
        lease_repository=leases,
        owner_id="node-a",
        lease_ttl_seconds=30,
    )
    second_scheduler = SchedulerService(
        lease_repository=leases,
        owner_id="node-b",
        lease_ttl_seconds=30,
    )
    first_scheduler.register_job(first_job)
    second_scheduler.register_job(second_job)

    running = asyncio.create_task(first_scheduler.execute_job("marketplace-sync"))
    await first_job.started.wait()
    await second_scheduler.execute_job("marketplace-sync")
    first_job.finish.set()
    await running

    print("First scheduler status:", first_scheduler.get_status("marketplace-sync"))
    print(
        "Second scheduler stats:", second_scheduler.get_statistics("marketplace-sync")
    )
    print("Active lease after completion:", await leases.get("marketplace-sync"))


if __name__ == "__main__":
    asyncio.run(main())
