from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from app.domain.marketplace import Marketplace
from app.repositories.queries.models import DashboardSummaryRead, DashboardWindow
from app.runtime.alerts import (
    AlertRoute,
    AlertSeverity,
    MarketplaceVolumeBaseline,
    OperationalAlert,
    OperationalAlertEngine,
    OperationalAlertRouter,
)
from app.services.marketplace_application_runner import MarketplaceRunResult
from app.services.marketplace_integration_execution import (
    MarketplaceIntegrationExecution,
    MarketplaceIntegrationExecutionBatch,
)

TENANT_ID = UUID("52000000-0000-4000-8000-000000000001")
GGSEL_ID = UUID("52000000-0000-4000-8000-000000000002")
PLAYEROK_ID = UUID("52000000-0000-4000-8000-000000000003")
FUNPAY_ID = UUID("52000000-0000-4000-8000-000000000004")
NOW = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


class RecordingSink:
    def __init__(self, *, fail: bool = False) -> None:
        self.alerts: list[OperationalAlert] = []
        self._fail = fail

    async def publish(self, alert: OperationalAlert) -> None:
        self.alerts.append(alert)
        if self._fail:
            raise RuntimeError("sensitive sink detail")


def test_engine_evaluates_polling_failures_errors_and_explicit_volume_drift() -> None:
    alerts = OperationalAlertEngine().evaluate(
        batch=_batch(),
        volume_baselines=(
            MarketplaceVolumeBaseline(
                tenant_id=TENANT_ID,
                integration_id=GGSEL_ID,
                minimum_offers_received=10,
            ),
        ),
    )

    assert {alert.code for alert in alerts} == {
        "marketplace_polling_failed",
        "marketplace_polling_skipped",
        "marketplace_processing_errors",
        "marketplace_source_volume_below_baseline",
    }
    drift = next(
        alert
        for alert in alerts
        if alert.code == "marketplace_source_volume_below_baseline"
    )
    assert drift.observed_value == 4
    assert drift.threshold == 10
    assert drift.tenant_id == TENANT_ID
    assert drift.integration_id == GGSEL_ID


def test_engine_does_not_invent_source_drift_without_baseline() -> None:
    alerts = OperationalAlertEngine().evaluate(batch=_batch())

    assert all(
        alert.code != "marketplace_source_volume_below_baseline" for alert in alerts
    )


def test_dashboard_alerts_cover_only_actual_failure_counters() -> None:
    alerts = OperationalAlertEngine().evaluate(dashboard=_dashboard())

    assert [(alert.code, alert.severity, alert.observed_value) for alert in alerts] == [
        ("content_generation_attempts_exhausted", AlertSeverity.CRITICAL, 1),
        ("publication_ambiguous", AlertSeverity.CRITICAL, 2),
        ("publication_permanently_failed", AlertSeverity.CRITICAL, 1),
        ("content_generation_failed", AlertSeverity.WARNING, 3),
        ("event_scoring_failed", AlertSeverity.WARNING, 1),
    ]
    assert all(alert.tenant_id == TENANT_ID for alert in alerts)


def test_alert_fingerprint_is_stable_when_observed_count_changes() -> None:
    first = OperationalAlert(
        code="publication_ambiguous",
        severity=AlertSeverity.CRITICAL,
        summary="Ambiguous publications require operator resolution.",
        observed_value=1,
        threshold=1,
        tenant_id=TENANT_ID,
    )
    second = OperationalAlert(
        code="publication_ambiguous",
        severity=AlertSeverity.CRITICAL,
        summary="Ambiguous publications require operator resolution.",
        observed_value=5,
        threshold=1,
        tenant_id=TENANT_ID,
    )

    assert first.fingerprint == second.fingerprint


def test_router_filters_by_severity_and_isolates_sink_failures() -> None:
    all_sink = RecordingSink()
    critical_sink = RecordingSink()
    failing_sink = RecordingSink(fail=True)
    alerts = OperationalAlertEngine().evaluate(
        batch=_batch(),
        dashboard=_dashboard(),
        volume_baselines=(
            MarketplaceVolumeBaseline(
                tenant_id=TENANT_ID,
                integration_id=GGSEL_ID,
                minimum_offers_received=10,
            ),
        ),
    )
    router = OperationalAlertRouter(
        (
            AlertRoute(name="all", sink=all_sink),
            AlertRoute(
                name="critical",
                sink=critical_sink,
                minimum_severity=AlertSeverity.CRITICAL,
            ),
            AlertRoute(
                name="failing",
                sink=failing_sink,
                codes=frozenset({"marketplace_polling_failed"}),
            ),
        )
    )

    result = run_async(router.route(alerts))

    assert result.alerts == 9
    assert result.attempted_deliveries == 14
    assert result.delivered == 13
    assert len(result.failures) == 1
    assert result.failures[0].route_name == "failing"
    assert result.failures[0].error_code == "RuntimeError"
    assert len(all_sink.alerts) == 9
    assert len(critical_sink.alerts) == 4
    assert len(failing_sink.alerts) == 1
    assert "sensitive sink detail" not in repr(result)


def test_router_rejects_duplicate_route_names() -> None:
    sink = RecordingSink()

    with pytest.raises(ValueError, match="route names must be unique"):
        OperationalAlertRouter(
            (
                AlertRoute(name="duplicate", sink=sink),
                AlertRoute(name="duplicate", sink=sink),
            )
        )


def _batch() -> MarketplaceIntegrationExecutionBatch:
    return MarketplaceIntegrationExecutionBatch(
        selected_integrations=3,
        executed_integrations=2,
        skipped_integrations=1,
        executions=(
            MarketplaceIntegrationExecution(
                integration_id=GGSEL_ID,
                tenant_id=TENANT_ID,
                marketplace="ggsel",
                source_url="https://ggsel.example/private?token=hidden",
                executed=True,
                result=_successful_result(),
            ),
            MarketplaceIntegrationExecution(
                integration_id=PLAYEROK_ID,
                tenant_id=TENANT_ID,
                marketplace="playerok",
                source_url="https://playerok.example/graphql",
                executed=True,
                error_code="TimeoutError",
                error_summary="private upstream response",
            ),
            MarketplaceIntegrationExecution(
                integration_id=FUNPAY_ID,
                tenant_id=TENANT_ID,
                marketplace="funpay",
                source_url=None,
                executed=False,
                skipped_reason="missing_source_url",
            ),
        ),
    )


def _successful_result() -> MarketplaceRunResult:
    return MarketplaceRunResult(
        marketplace=Marketplace.GGSEL,
        offers_received=4,
        offers_persisted=4,
        comparison_results=0,
        snapshots_created=4,
        snapshots_persisted=4,
        skipped_offers=0,
        price_changes_detected=0,
        event_candidates_built=0,
        events_created=0,
        events_existing=0,
        skipped_event_candidates=0,
        event_ids=(),
        events_scored=0,
        content_items_generated=0,
        persistence_committed=True,
        errors=("malformed source item",),
        tenant_id=TENANT_ID,
    )


def _dashboard() -> DashboardSummaryRead:
    return DashboardSummaryRead(
        window=DashboardWindow(
            starts_at=NOW - timedelta(hours=24),
            ends_at=NOW,
            tenant_id=TENANT_ID,
        ),
        total_new_market_events=10,
        events_awaiting_scoring=0,
        scoring_failures=1,
        generated_content_pending=0,
        generated_content_failed=3,
        generated_content_attempts_exhausted=1,
        generated_content_awaiting_review=0,
        approved_content_awaiting_publication=0,
        publications_pending=0,
        publications_retryable=0,
        publications_permanently_failed=1,
        publications_ambiguous=2,
        publications_published=4,
        latest_event_activity_at=NOW,
        latest_publication_at=NOW,
    )
