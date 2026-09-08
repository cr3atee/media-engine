from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from app.config.settings import SchedulerSettings
from app.runtime.bootstrap import create_memory_runtime_components
from app.runtime.process import RuntimeJobConfig, RuntimeProcess
from app.runtime.worker import register_enabled_marketplace_integrations_job
from app.scheduler.jobs import JobExecutionState


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run async runtime worker checks without an external pytest plugin."""
    return asyncio.run(awaitable)


def test_worker_registers_enabled_marketplace_integrations_job() -> None:
    process = RuntimeProcess(
        create_memory_runtime_components(
            SchedulerSettings(lease_enabled=False, tick_seconds=0.1),
        ),
    )

    register_enabled_marketplace_integrations_job(
        process,
        runner_factories={},
        config=RuntimeJobConfig(interval_seconds=60, enabled=False),
    )

    assert process.list_statuses()[0].name == "enabled-marketplace-integrations"
    assert process.list_statuses()[0].state is JobExecutionState.REGISTERED
    assert process.list_schedule_statuses()[0].interval_seconds == 60


def test_worker_job_delegates_to_integration_service() -> None:
    process = RuntimeProcess(
        create_memory_runtime_components(
            SchedulerSettings(lease_enabled=False, tick_seconds=0.1),
        ),
    )
    register_enabled_marketplace_integrations_job(process, runner_factories={})

    run_async(process.execute_once("enabled-marketplace-integrations"))

    assert process.list_statuses()[0].state is JobExecutionState.SUCCEEDED
