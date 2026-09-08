"""Run the MediaEngine worker process."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config.settings import settings
from app.core.http_client import HttpClient
from app.runtime.bootstrap import create_default_runtime_components
from app.runtime.marketplaces import create_marketplace_runner_factories
from app.runtime.process import RuntimeJobConfig, RuntimeProcess
from app.runtime.worker import register_enabled_marketplace_integrations_job


def parse_args() -> argparse.Namespace:
    """Parse worker command-line options."""
    parser = argparse.ArgumentParser(description="Run MediaEngine worker.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Execute enabled marketplace integrations once and exit.",
    )
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=None,
        help="Run periodic Scheduler execution for this many seconds.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=300,
        help="Enabled marketplace integration polling interval.",
    )
    return parser.parse_args()


async def main() -> int:
    """Run one bounded or periodic MediaEngine worker process."""
    args = parse_args()
    components = create_default_runtime_components(settings)
    process = RuntimeProcess(components)

    async with HttpClient() as http_client:
        runner_factories = create_marketplace_runner_factories(
            http_client=http_client,
            repository_scope_factory=components.repository_scope_factory,
        )
        register_enabled_marketplace_integrations_job(
            process,
            runner_factories=runner_factories,
            config=RuntimeJobConfig(
                interval_seconds=None if args.once else args.interval_seconds,
                enabled=not args.once,
                retry_count=1,
                retry_delay_seconds=1.0,
            ),
        )

        job_name = process.list_statuses()[0].name
        if args.once:
            await process.execute_once(job_name)
            _print_statuses(process)
            return 0

        process.start()
        try:
            if args.duration_seconds is None:
                await asyncio.Event().wait()
            else:
                await asyncio.sleep(args.duration_seconds)
        finally:
            await process.stop()
            _print_statuses(process)

    return 0


def _print_statuses(process: RuntimeProcess) -> None:
    print("=== WORKER STATUS ===")
    for status in process.list_statuses():
        print(
            f"{status.name}: state={status.state.value} "
            f"runs={status.run_count} failures={status.failure_count} "
            f"error={status.last_error}"
        )
    print("=== WORKER STATISTICS ===")
    for statistics in process.list_statistics():
        print(
            f"{statistics.name}: total={statistics.total_executions} "
            f"success={statistics.successful_executions} "
            f"failed={statistics.failed_executions} "
            f"retries={statistics.retry_attempts} "
            f"lease_skips={statistics.lease_skips}"
        )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
