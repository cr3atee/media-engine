"""Run the MediaEngine worker process."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config.settings import settings
from app.core.http_client import HttpClient
from app.core.logging import setup_logging
from app.runtime.alert_lifecycle import AlertLifecyclePolicy, OperationalAlertLifecycle
from app.runtime.alert_monitor import RuntimeAlertMonitor
from app.runtime.alert_sinks import StructuredLoggingAlertSink
from app.runtime.bootstrap import RuntimeComponents, create_default_runtime_components
from app.runtime.marketplaces import create_marketplace_runner_factories
from app.runtime.metrics import PrometheusTextfileWriter, RuntimeMetricsExporter
from app.runtime.monitoring import RuntimeMonitor
from app.runtime.process import RuntimeJobConfig, RuntimeProcess
from app.runtime.worker import (
    register_enabled_marketplace_integrations_job,
    register_marketplace_polling_retention_job,
)
from app.services.marketplace_credentials import (
    EnvironmentMarketplaceCredentialResolver,
)
from app.services.marketplace_integration_execution import (
    MarketplaceIntegrationExecutionBatch,
)


@dataclass(slots=True, frozen=True)
class WorkerArguments:
    """Validated worker process command-line options."""

    once: bool
    duration_seconds: float | None
    interval_seconds: int
    retry_count: int
    retry_delay_seconds: float
    timeout_seconds: float | None
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
        "--retry-count",
        type=_non_negative_int,
        default=1,
        help="Marketplace job retries after the initial attempt.",
    )
    parser.add_argument(
        "--retry-delay-seconds",
        type=_non_negative_float,
        default=1.0,
        help="Delay between marketplace job attempts.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=_positive_float,
        default=None,
        help="Optional timeout for each marketplace job attempt.",
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
        retry_count=namespace.retry_count,
        retry_delay_seconds=namespace.retry_delay_seconds,
        timeout_seconds=namespace.timeout_seconds,
        metrics_file=namespace.metrics_file,
        metrics_refresh_seconds=namespace.metrics_refresh_seconds,
    )


async def main() -> int:
    """Run one bounded or periodic MediaEngine worker process."""
    args = parse_args()
    setup_logging()
    components = create_default_runtime_components(settings)
    process = RuntimeProcess(components)
    alert_monitor = _create_alert_monitor(components)
    metrics_writer = (
        PrometheusTextfileWriter(args.metrics_file)
        if args.metrics_file is not None
        else None
    )

    async with HttpClient() as http_client:
        runner_factories = create_marketplace_runner_factories(
            http_client=http_client,
            repository_scope_factory=components.repository_scope_factory,
            credential_resolver=EnvironmentMarketplaceCredentialResolver(),
        )
        register_enabled_marketplace_integrations_job(
            process,
            runner_factories=runner_factories,
            config=RuntimeJobConfig(
                interval_seconds=None if args.once else args.interval_seconds,
                enabled=not args.once,
                retry_count=args.retry_count,
                retry_delay_seconds=args.retry_delay_seconds,
                timeout_seconds=args.timeout_seconds,
            ),
        )

        if not args.once:
            _register_polling_retention(process)

        job_name = "enabled-marketplace-integrations"
        if args.once:
            await process.execute_once(job_name)
            await _evaluate_alerts(process, job_name, alert_monitor)
            _write_metrics(process, job_name, metrics_writer)
            _print_marketplace_result(process, job_name)
            _print_statuses(process)
            return 0

        if metrics_writer is not None:
            _write_metrics(process, job_name, metrics_writer)
        shutdown_event = asyncio.Event()
        remove_termination_handler = _install_termination_handler(shutdown_event)
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
        alert_task = (
            asyncio.create_task(
                _refresh_alerts(
                    process,
                    job_name,
                    alert_monitor,
                    refresh_seconds=settings.alerting.evaluation_interval_seconds,
                )
            )
            if alert_monitor is not None
            else None
        )
        try:
            await _wait_for_shutdown(
                shutdown_event,
                duration_seconds=args.duration_seconds,
            )
        finally:
            try:
                await process.stop()
                if metrics_task is not None:
                    metrics_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await metrics_task
                if alert_task is not None:
                    alert_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await alert_task
                    await _evaluate_alerts(process, job_name, alert_monitor)
                _write_metrics(process, job_name, metrics_writer)
                _print_marketplace_result(process, job_name)
                _print_statuses(process)
            finally:
                remove_termination_handler()

    return 0


def _register_polling_retention(process: RuntimeProcess) -> None:
    configuration = settings.polling_retention
    if not configuration.enabled:
        return
    interval_seconds = configuration.interval_seconds
    retain_for_seconds = configuration.retain_for_seconds
    keep_latest = configuration.keep_latest_per_integration
    batch_size = configuration.batch_size
    timeout_seconds = configuration.timeout_seconds
    if (
        interval_seconds is None
        or retain_for_seconds is None
        or keep_latest is None
        or batch_size is None
        or timeout_seconds is None
    ):
        raise RuntimeError("Enabled polling retention policy is incomplete.")
    register_marketplace_polling_retention_job(
        process,
        retain_for_seconds=retain_for_seconds,
        keep_latest_per_integration=keep_latest,
        batch_size=batch_size,
        config=RuntimeJobConfig(
            interval_seconds=interval_seconds,
            retry_count=configuration.retry_count,
            retry_delay_seconds=configuration.retry_delay_seconds,
            timeout_seconds=timeout_seconds,
        ),
    )


def _install_termination_handler(
    shutdown_event: asyncio.Event,
) -> Callable[[], None]:
    """Translate container SIGTERM into the normal async shutdown path."""
    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGTERM, shutdown_event.set)
    except (NotImplementedError, RuntimeError):
        return lambda: None

    def remove_handler() -> None:
        loop.remove_signal_handler(signal.SIGTERM)

    return remove_handler


async def _wait_for_shutdown(
    shutdown_event: asyncio.Event,
    *,
    duration_seconds: float | None,
) -> None:
    """Wait for SIGTERM or an optional bounded worker duration."""
    if duration_seconds is None:
        await shutdown_event.wait()
        return
    try:
        await asyncio.wait_for(shutdown_event.wait(), timeout=duration_seconds)
    except TimeoutError:
        return


def _create_alert_monitor(
    components: RuntimeComponents,
) -> RuntimeAlertMonitor | None:
    if not settings.alerting.enabled:
        return None
    read_scope_factory = components.read_repository_scope_factory
    if read_scope_factory is None:
        raise RuntimeError("Alerting requires a read repository scope.")
    return RuntimeAlertMonitor(
        read_repository_scope_factory=read_scope_factory,
        lifecycle=OperationalAlertLifecycle(
            AlertLifecyclePolicy(
                reminder_interval=timedelta(
                    seconds=settings.alerting.reminder_interval_seconds
                )
            )
        ),
        sink=StructuredLoggingAlertSink(),
        dashboard_window=timedelta(seconds=settings.alerting.dashboard_window_seconds),
    )


async def _refresh_alerts(
    process: RuntimeProcess,
    job_name: str,
    monitor: RuntimeAlertMonitor,
    *,
    refresh_seconds: float,
) -> None:
    while True:
        await _evaluate_alerts(process, job_name, monitor)
        await asyncio.sleep(refresh_seconds)


async def _evaluate_alerts(
    process: RuntimeProcess,
    job_name: str,
    monitor: RuntimeAlertMonitor | None,
) -> None:
    if monitor is None:
        return
    result = process.get_last_result(job_name)
    batch = result if isinstance(result, MarketplaceIntegrationExecutionBatch) else None
    try:
        evaluation = await monitor.evaluate(
            batch=batch,
            observed_at=datetime.now(UTC),
        )
    except Exception as error:
        print(
            f"Operational alert evaluation failed: {type(error).__name__}.",
            file=sys.stderr,
        )
        return
    if evaluation.dashboard_error_code is not None:
        print(
            "Operational alert dashboard read failed: "
            f"{evaluation.dashboard_error_code}.",
            file=sys.stderr,
        )
    if evaluation.delivery_failures:
        print(
            "Operational alert delivery failures: "
            f"{len(evaluation.delivery_failures)}.",
            file=sys.stderr,
        )


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


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("Value must be greater than or equal to zero.")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("Value must be greater than or equal to zero.")
    return parsed


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
