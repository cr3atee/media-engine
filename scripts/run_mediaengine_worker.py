"""Run the MediaEngine worker process."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config.settings import settings
from app.core.http_client import HttpClient
from app.runtime.bootstrap import create_default_runtime_components
from app.runtime.marketplaces import create_marketplace_runner_factories
from app.runtime.metrics import PrometheusTextfileWriter, RuntimeMetricsExporter
from app.runtime.monitoring import RuntimeMonitor
from app.runtime.process import RuntimeJobConfig, RuntimeProcess
from app.runtime.worker import register_enabled_marketplace_integrations_job
from app.services.marketplace_integration_execution import (
    MarketplaceIntegrationExecutionBatch,
)


@dataclass(slots=True, frozen=True)
class WorkerArguments:
    """Validated worker process command-line options."""

    once: bool
    duration_seconds: float | None
    interval_seconds: int
    metrics_file: Path | None
    metrics_refresh_seconds: float


def parse_args(argv: Sequence[str] | None = None) -> WorkerArguments:
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
    parser.add_argument(
        "--metrics-file",
        type=Path,
        default=None,
        help="Atomically write Prometheus textfile metrics to this path.",
    )
    parser.add_argument(
        "--metrics-refresh-seconds",
        type=_positive_float,
        default=5.0,
        help="Metrics textfile refresh interval for periodic execution.",
    )
    namespace = parser.parse_args(argv)
    return WorkerArguments(
        once=namespace.once,
        duration_seconds=namespace.duration_seconds,
        interval_seconds=namespace.interval_seconds,
        metrics_file=namespace.metrics_file,
        metrics_refresh_seconds=namespace.metrics_refresh_seconds,
    )


async def main() -> int:
    """Run one bounded or periodic MediaEngine worker process."""
    args = parse_args()
    components = create_default_runtime_components(settings)
    process = RuntimeProcess(components)
    metrics_writer = (
        PrometheusTextfileWriter(args.metrics_file)
        if args.metrics_file is not None
        else None
    )

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
            _write_metrics(process, job_name, metrics_writer)
            _print_marketplace_result(process, job_name)
            _print_statuses(process)
            return 0

        if metrics_writer is not None:
            _write_metrics(process, job_name, metrics_writer)
        process.start()
        metrics_task = (
            asyncio.create_task(
                _refresh_metrics(
                    process,
                    job_name,
                    metrics_writer,
                    refresh_seconds=args.metrics_refresh_seconds,
                )
            )
            if metrics_writer is not None
            else None
        )
        try:
            if args.duration_seconds is None:
                await asyncio.Event().wait()
            else:
                await asyncio.sleep(args.duration_seconds)
        finally:
            await process.stop()
            if metrics_task is not None:
                metrics_task.cancel()
                with suppress(asyncio.CancelledError):
                    await metrics_task
            _write_metrics(process, job_name, metrics_writer)
            _print_marketplace_result(process, job_name)
            _print_statuses(process)

    return 0


async def _refresh_metrics(
    process: RuntimeProcess,
    job_name: str,
    writer: PrometheusTextfileWriter,
    *,
    refresh_seconds: float,
) -> None:
    """Refresh process metrics independently from job execution cadence."""
    while True:
        try:
            _write_metrics(process, job_name, writer)
        except OSError as error:
            print(
                f"Metrics export failed: {type(error).__name__}.",
                file=sys.stderr,
            )
        await asyncio.sleep(refresh_seconds)


def _write_metrics(
    process: RuntimeProcess,
    job_name: str,
    writer: PrometheusTextfileWriter | None,
) -> None:
    if writer is None:
        return
    result = process.get_last_result(job_name)
    batch = result if isinstance(result, MarketplaceIntegrationExecutionBatch) else None
    writer.write(RuntimeMetricsExporter().render(process, batch))


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


def _print_marketplace_result(process: RuntimeProcess, job_name: str) -> None:
    result = process.get_last_result(job_name)
    if not isinstance(result, MarketplaceIntegrationExecutionBatch):
        return

    diagnostic = RuntimeMonitor().summarize_marketplace_batch(result)
    print("=== MARKETPLACE POLLING ===")
    print(f"Selected integrations: {diagnostic.selected_integrations}")
    print(f"Executed integrations: {diagnostic.executed_integrations}")
    print(f"Skipped integrations: {diagnostic.skipped_integrations}")
    print(f"Failed integrations: {diagnostic.failed_integrations}")
    for execution in diagnostic.executions:
        print(
            f"{execution.marketplace}: executed={execution.executed} "
            f"source_url_present={execution.source_url_present} "
            f"skipped={execution.skipped_reason} result={execution.result_type} "
            f"error={execution.error_code}"
        )
        if execution.run is not None:
            print(
                f"  offers={execution.run.offers_received} "
                f"persisted={execution.run.offers_persisted} "
                f"snapshots={execution.run.snapshots_persisted}/"
                f"{execution.run.snapshots_created} "
                f"price_changes={execution.run.price_changes_detected} "
                f"events={execution.run.events_created} "
                f"errors={len(execution.run.errors)}"
            )


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("Value must be greater than zero.")
    return parsed


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
