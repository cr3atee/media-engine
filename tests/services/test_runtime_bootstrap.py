from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config.settings import SchedulerSettings, Settings
from app.repositories.postgres import PostgresOfferRepository
from app.runtime.bootstrap import (
    RuntimeComponents,
    create_default_runtime_components,
    create_memory_runtime_components,
    create_postgres_runtime_components,
)
from app.scheduler.jobs import BaseJob, JobExecutionState


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run async runtime checks without requiring an external pytest plugin."""
    return asyncio.run(awaitable)


class CountingJob(BaseJob):
    """Minimal scheduler job used to verify runtime wiring."""

    def __init__(self) -> None:
        """Initialize the job counter."""
        super().__init__("counting")
        self.calls = 0

    def run(self) -> object:
        """Record one execution."""
        self.calls += 1
        return None


def test_memory_runtime_components_wire_repository_scope_and_scheduler() -> None:
    components = create_memory_runtime_components(
        SchedulerSettings(lease_enabled=False, tick_seconds=0.1),
    )
    job = CountingJob()
    components.scheduler.register_job(job)

    async def scenario() -> int:
        async with components.repository_scope_factory() as repositories:
            await repositories.offers.list_all()
        await components.scheduler.execute_job("counting")
        return job.calls

    assert run_async(scenario()) == 1
    assert components.scheduler.get_status("counting").state is (
        JobExecutionState.SUCCEEDED
    )


def test_postgres_runtime_components_bind_scope_to_postgres_repositories() -> None:
    session_factory = async_sessionmaker(expire_on_commit=False)
    components = create_postgres_runtime_components(
        SchedulerSettings(lease_enabled=False),
        session_factory=session_factory,
    )

    async def inspect_scope() -> str:
        async with components.repository_scope_factory() as repositories:
            return type(repositories.offers).__name__

    assert isinstance(components, RuntimeComponents)
    assert run_async(inspect_scope()) == PostgresOfferRepository.__name__


def test_postgres_runtime_components_allow_scheduler_leases_when_enabled() -> None:
    session_factory = async_sessionmaker(expire_on_commit=False)

    components = create_postgres_runtime_components(
        SchedulerSettings(
            lease_enabled=True,
            owner_id="runtime-test",
            lease_ttl_seconds=30,
        ),
        session_factory=session_factory,
    )

    assert isinstance(components, RuntimeComponents)


def test_default_runtime_components_use_project_settings() -> None:
    session_factory = async_sessionmaker(expire_on_commit=False)
    scheduler_settings = SchedulerSettings(lease_enabled=False)

    components = create_default_runtime_components(
        Settings(scheduler=scheduler_settings),
        session_factory=session_factory,
    )

    assert isinstance(components, RuntimeComponents)
