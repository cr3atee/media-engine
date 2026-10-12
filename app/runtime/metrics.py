from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.scheduler.jobs import JobExecutionState, JobExecutionStatus
from app.scheduler.service import JobRuntimeStatistics
from app.services.marketplace_application_runner import MarketplaceRunResult
from app.services.marketplace_integration_execution import (
    MarketplaceIntegrationExecutionBatch,
)


class RuntimeMetricsSource(Protocol):
    """Minimal runtime state required by the metrics exporter."""

    def list_statuses(self) -> tuple[JobExecutionStatus, ...]:
        """Return current Scheduler job states."""

    def list_statistics(self) -> tuple[JobRuntimeStatistics, ...]:
        """Return process-local Scheduler counters."""


@dataclass(slots=True)
class _MarketplaceMetrics:
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    offers_received: int = 0
    offers_persisted: int = 0
    snapshots_created: int = 0
    snapshots_persisted: int = 0
    price_changes_detected: int = 0
    events_created: int = 0
    processing_errors: int = 0


class RuntimeMetricsExporter:
    """Render bounded runtime state in Prometheus text exposition format."""

    def render(
        self,
        source: RuntimeMetricsSource,
        batch: MarketplaceIntegrationExecutionBatch | None = None,
    ) -> str:
        """Return deterministic low-cardinality metrics without sensitive data."""
        lines: list[str] = []
        self._render_scheduler(lines, source)
        if batch is not None:
            self._render_marketplace_batch(lines, batch)
        return "\n".join(lines) + "\n"

    def _render_scheduler(
        self,
        lines: list[str],
        source: RuntimeMetricsSource,
    ) -> None:
        statuses = sorted(source.list_statuses(), key=lambda status: status.name)
        statistics = sorted(
            source.list_statistics(),
            key=lambda statistic: statistic.name,
        )
        _start_family(
            lines,
            "mediaengine_scheduler_job_state",
            "Current Scheduler job state (exactly one state is 1 per job).",
            "gauge",
        )
        for status in statuses:
            for state in JobExecutionState:
                _sample(
                    lines,
                    "mediaengine_scheduler_job_state",
                    int(status.state is state),
                    job=status.name,
                    state=state.value,
                )

        scheduler_counters = (
            (
                "mediaengine_scheduler_job_executions_total",
                "Scheduler executions observed by this worker process.",
                "total_executions",
            ),
            (
                "mediaengine_scheduler_job_successes_total",
                "Successful Scheduler executions observed by this worker process.",
                "successful_executions",
            ),
            (
                "mediaengine_scheduler_job_failures_total",
                "Failed Scheduler executions observed by this worker process.",
                "failed_executions",
            ),
            (
                "mediaengine_scheduler_job_retries_total",
                "Scheduler retry attempts observed by this worker process.",
                "retry_attempts",
            ),
            (
                "mediaengine_scheduler_job_lease_skips_total",
                "Scheduler executions skipped because another worker held the lease.",
                "lease_skips",
            ),
        )
        for metric_name, help_text, attribute in scheduler_counters:
            _start_family(lines, metric_name, help_text, "counter")
            for statistic in statistics:
                _sample(
                    lines,
                    metric_name,
                    getattr(statistic, attribute),
                    job=statistic.name,
                )

    def _render_marketplace_batch(
        self,
        lines: list[str],
        batch: MarketplaceIntegrationExecutionBatch,
    ) -> None:
        _start_family(
            lines,
            "mediaengine_marketplace_batch_integrations",
            "Integration counts in the latest completed polling batch.",
            "gauge",
        )
        for outcome, value in (
            ("selected", batch.selected_integrations),
            ("executed", batch.executed_integrations),
            ("skipped", batch.skipped_integrations),
            ("failed", batch.failed_integrations),
        ):
            _sample(
                lines,
                "mediaengine_marketplace_batch_integrations",
                value,
                outcome=outcome,
            )

        by_marketplace: dict[str, _MarketplaceMetrics] = {}
        for execution in batch.executions:
            metrics = by_marketplace.setdefault(
                execution.marketplace,
                _MarketplaceMetrics(),
            )
            if not execution.executed:
                metrics.skipped += 1
            elif execution.succeeded:
                metrics.succeeded += 1
            else:
                metrics.failed += 1

            result = execution.result
            if isinstance(result, MarketplaceRunResult):
                metrics.offers_received += result.offers_received
                metrics.offers_persisted += result.offers_persisted
                metrics.snapshots_created += result.snapshots_created
                metrics.snapshots_persisted += result.snapshots_persisted
                metrics.price_changes_detected += result.price_changes_detected
                metrics.events_created += result.events_created
                metrics.processing_errors += len(result.errors)

        _start_family(
            lines,
            "mediaengine_marketplace_polling_integrations",
            "Integration outcomes in the latest batch by marketplace.",
            "gauge",
        )
        for marketplace, metrics in sorted(by_marketplace.items()):
            for outcome, value in (
                ("succeeded", metrics.succeeded),
                ("failed", metrics.failed),
                ("skipped", metrics.skipped),
            ):
                _sample(
                    lines,
                    "mediaengine_marketplace_polling_integrations",
                    value,
                    marketplace=marketplace,
                    outcome=outcome,
                )

        marketplace_gauges = (
            (
                "mediaengine_marketplace_offers_received",
                "Offers received in the latest batch by marketplace.",
                "offers_received",
            ),
            (
                "mediaengine_marketplace_offers_persisted",
                "Offers persisted in the latest batch by marketplace.",
                "offers_persisted",
            ),
            (
                "mediaengine_marketplace_snapshots_created",
                "Price snapshots created in the latest batch by marketplace.",
                "snapshots_created",
            ),
            (
                "mediaengine_marketplace_snapshots_persisted",
                "Price snapshots persisted in the latest batch by marketplace.",
                "snapshots_persisted",
            ),
            (
                "mediaengine_marketplace_price_changes_detected",
                "Price changes detected in the latest batch by marketplace.",
                "price_changes_detected",
            ),
            (
                "mediaengine_marketplace_events_created",
                "Market events created in the latest batch by marketplace.",
                "events_created",
            ),
            (
                "mediaengine_marketplace_processing_errors",
                "Non-fatal processing errors in the latest batch by marketplace.",
                "processing_errors",
            ),
        )
        for metric_name, help_text, attribute in marketplace_gauges:
            _start_family(lines, metric_name, help_text, "gauge")
            for marketplace, metrics in sorted(by_marketplace.items()):
                _sample(
                    lines,
                    metric_name,
                    getattr(metrics, attribute),
                    marketplace=marketplace,
                )


class PrometheusTextfileWriter:
    """Atomically replace one Prometheus textfile collector payload."""

    def __init__(self, path: Path) -> None:
        """Bind the writer to an operator-selected output path."""
        self._path = path

    @property
    def path(self) -> Path:
        """Return the configured final metrics path."""
        return self._path

    def write(self, payload: str) -> None:
        """Write a complete payload without exposing a partially written file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f".{self._path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(payload, encoding="utf-8", newline="\n")
            temporary.replace(self._path)
        finally:
            temporary.unlink(missing_ok=True)


def _start_family(
    lines: list[str],
    name: str,
    help_text: str,
    metric_type: str,
) -> None:
    lines.extend((f"# HELP {name} {help_text}", f"# TYPE {name} {metric_type}"))


def _sample(
    lines: list[str],
    name: str,
    value: int,
    **labels: str,
) -> None:
    rendered_labels = ""
    if labels:
        rendered_labels = (
            "{"
            + ",".join(
                f'{key}="{_escape_label(label)}"'
                for key, label in sorted(labels.items())
            )
            + "}"
        )
    lines.append(f"{name}{rendered_labels} {value}")


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
