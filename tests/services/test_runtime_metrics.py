from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from app.domain.marketplace import Marketplace
from app.runtime.metrics import PrometheusTextfileWriter, RuntimeMetricsExporter
from app.scheduler.jobs import JobExecutionState, JobExecutionStatus
from app.scheduler.service import JobRuntimeStatistics
from app.services.marketplace_application_runner import MarketplaceRunResult
from app.services.marketplace_integration_execution import (
    MarketplaceIntegrationExecution,
    MarketplaceIntegrationExecutionBatch,
)
from scripts.run_mediaengine_worker import parse_args


class MetricsSource:
    """Deterministic Scheduler metrics source for exporter tests."""

    def list_statuses(self) -> tuple[JobExecutionStatus, ...]:
        return (
            JobExecutionStatus(
                name='marketplace-"worker"',
                state=JobExecutionState.SUCCEEDED,
                run_count=3,
            ),
        )

    def list_statistics(self) -> tuple[JobRuntimeStatistics, ...]:
        return (
            JobRuntimeStatistics(
                name='marketplace-"worker"',
                total_executions=3,
                successful_executions=2,
                failed_executions=1,
                retry_attempts=1,
                lease_skips=2,
                last_successful_run=datetime(2026, 10, 12, tzinfo=UTC),
            ),
        )


def test_runtime_metrics_are_bounded_aggregates_without_sensitive_labels() -> None:
    batch = MarketplaceIntegrationExecutionBatch(
        selected_integrations=3,
        executed_integrations=2,
        skipped_integrations=1,
        executions=(
            _successful_execution(),
            MarketplaceIntegrationExecution(
                integration_id=UUID(int=2),
                tenant_id=UUID(int=20),
                marketplace="playerok",
                source_url="https://secret.example/source?token=private",
                executed=True,
                error_code="TimeoutError",
                error_summary="Marketplace polling failed.",
            ),
            MarketplaceIntegrationExecution(
                integration_id=UUID(int=3),
                tenant_id=UUID(int=30),
                marketplace="funpay",
                source_url=None,
                executed=False,
                skipped_reason="missing_source_url",
            ),
        ),
    )

    payload = RuntimeMetricsExporter().render(MetricsSource(), batch)

    assert (
        'mediaengine_scheduler_job_state{job="marketplace-\\"worker\\"",'
        'state="succeeded"} 1'
    ) in payload
    assert 'mediaengine_marketplace_batch_integrations{outcome="failed"} 1' in payload
    assert (
        'mediaengine_marketplace_polling_integrations{marketplace="ggsel",'
        'outcome="succeeded"} 1'
    ) in payload
    assert 'mediaengine_marketplace_offers_received{marketplace="ggsel"} 10' in payload
    assert 'mediaengine_marketplace_processing_errors{marketplace="ggsel"} 1' in payload
    assert "secret.example" not in payload
    assert "private" not in payload
    assert str(UUID(int=20)) not in payload
    assert "Marketplace polling failed" not in payload


def test_runtime_metrics_without_batch_still_expose_scheduler_state() -> None:
    payload = RuntimeMetricsExporter().render(MetricsSource())

    assert "mediaengine_scheduler_job_executions_total" in payload
    assert "mediaengine_marketplace_batch_integrations" not in payload


def test_prometheus_textfile_writer_replaces_complete_payload(tmp_path: Path) -> None:
    path = tmp_path / "collector" / "mediaengine.prom"
    writer = PrometheusTextfileWriter(path)

    writer.write("first 1\n")
    writer.write("second 2\n")

    assert writer.path == path
    assert path.read_text(encoding="utf-8") == "second 2\n"
    assert tuple(path.parent.glob("*.tmp")) == ()


def test_worker_metrics_export_is_opt_in() -> None:
    arguments = parse_args(["--once"])

    assert arguments.metrics_file is None
    assert arguments.metrics_refresh_seconds == 5.0
    assert arguments.retry_count == 1
    assert arguments.retry_delay_seconds == 1.0
    assert arguments.timeout_seconds is None


def test_worker_accepts_metrics_textfile_configuration(tmp_path: Path) -> None:
    path = tmp_path / "mediaengine.prom"

    arguments = parse_args(
        [
            "--metrics-file",
            str(path),
            "--metrics-refresh-seconds",
            "0.5",
            "--retry-count",
            "2",
            "--retry-delay-seconds",
            "3",
            "--timeout-seconds",
            "45",
        ]
    )

    assert arguments.metrics_file == path
    assert arguments.metrics_refresh_seconds == 0.5
    assert arguments.retry_count == 2
    assert arguments.retry_delay_seconds == 3
    assert arguments.timeout_seconds == 45


def _successful_execution() -> MarketplaceIntegrationExecution:
    result = MarketplaceRunResult(
        marketplace=Marketplace.GGSEL,
        offers_received=10,
        offers_persisted=9,
        comparison_results=0,
        snapshots_created=8,
        snapshots_persisted=7,
        skipped_offers=1,
        price_changes_detected=2,
        event_candidates_built=1,
        events_created=1,
        events_existing=0,
        skipped_event_candidates=0,
        event_ids=(UUID(int=100),),
        events_scored=0,
        content_items_generated=0,
        persistence_committed=True,
        errors=("malformed offer",),
    )
    return MarketplaceIntegrationExecution(
        integration_id=UUID(int=1),
        tenant_id=UUID(int=10),
        marketplace="ggsel",
        source_url="https://ggsel.example/catalog",
        executed=True,
        result=result,
    )
