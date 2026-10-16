"""Verify deterministic operational alert evaluation and routing offline."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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

TENANT_ID = UUID("53000000-0000-4000-8000-000000000001")
GGSEL_ID = UUID("53000000-0000-4000-8000-000000000002")
PLAYEROK_ID = UUID("53000000-0000-4000-8000-000000000003")
FUNPAY_ID = UUID("53000000-0000-4000-8000-000000000004")
NOW = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)
SENSITIVE_VALUES = (
    "must-not-leak",
    "private upstream response",
    "private sink response",
    "https://ggsel.example",
)


@dataclass(slots=True)
class Verification:
    """Count deterministic operational-alert assertions."""

    checks: int = 0

    def expect(self, condition: bool, label: str) -> None:
        """Record one check or stop with a useful diagnostic."""
        if not condition:
            raise RuntimeError(f"Operational alert verification failed: {label}.")
        self.checks += 1


class RecordingSink:
    """Record routed alerts and optionally simulate an isolated failure."""

    def __init__(self, *, fail: bool = False) -> None:
        self.alerts: list[OperationalAlert] = []
        self._fail = fail

    async def publish(self, alert: OperationalAlert) -> None:
        """Record one alert before returning or raising."""
        self.alerts.append(alert)
        if self._fail:
            raise RuntimeError("private sink response")


async def verify() -> Verification:
    """Exercise alert conditions, stable identity, routing, and redaction."""
    verification = Verification()
    engine = OperationalAlertEngine()
    alerts = engine.evaluate(
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

    expected_codes = {
        "content_generation_failed",
        "event_scoring_failed",
        "marketplace_polling_failed",
        "marketplace_polling_skipped",
        "marketplace_processing_errors",
        "marketplace_source_volume_below_baseline",
        "publication_ambiguous",
        "publication_permanently_failed",
    }
    verification.expect(len(alerts) == 8, "eight conditions evaluated")
    verification.expect(
        {alert.code for alert in alerts} == expected_codes,
        "expected alert codes returned",
    )
    verification.expect(
        sum(alert.severity is AlertSeverity.CRITICAL for alert in alerts) == 3,
        "critical severity classification",
    )
    drift = next(
        alert
        for alert in alerts
        if alert.code == "marketplace_source_volume_below_baseline"
    )
    verification.expect(
        (drift.observed_value, drift.threshold) == (4, 10),
        "explicit source-volume threshold",
    )
    verification.expect(
        (drift.tenant_id, drift.integration_id) == (TENANT_ID, GGSEL_ID),
        "tenant and integration scope preserved",
    )
    verification.expect(
        alerts
        == engine.evaluate(
            batch=_batch(),
            dashboard=_dashboard(),
            volume_baselines=(
                MarketplaceVolumeBaseline(
                    tenant_id=TENANT_ID,
                    integration_id=GGSEL_ID,
                    minimum_offers_received=10,
                ),
            ),
        ),
        "evaluation is deterministic",
    )
    verification.expect(
        all(
            alert.code != "marketplace_source_volume_below_baseline"
            for alert in engine.evaluate(batch=_batch())
        ),
        "source drift requires an explicit baseline",
    )
    alert_text = repr(alerts)
    verification.expect(
        all(value not in alert_text for value in SENSITIVE_VALUES),
        "source URLs and raw errors are redacted",
    )

    changed_dashboard_alert = next(
        alert
        for alert in engine.evaluate(dashboard=_dashboard(ambiguous=9))
        if alert.code == "publication_ambiguous"
    )
    original_dashboard_alert = next(
        alert for alert in alerts if alert.code == "publication_ambiguous"
    )
    verification.expect(
        changed_dashboard_alert.fingerprint == original_dashboard_alert.fingerprint,
        "fingerprint is stable across observed counts",
    )

    all_sink = RecordingSink()
    critical_sink = RecordingSink()
    failing_sink = RecordingSink(fail=True)
    result = await OperationalAlertRouter(
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
    ).route(alerts)
    verification.expect(result.alerts == 8, "all unique alerts routed")
    verification.expect(result.attempted_deliveries == 12, "route filters applied")
    verification.expect(result.delivered == 11, "successful deliveries counted")
    verification.expect(len(result.failures) == 1, "sink failure isolated")
    verification.expect(
        result.failures[0].error_code == "RuntimeError",
        "failure reduced to a safe error category",
    )
    verification.expect(
        (len(all_sink.alerts), len(critical_sink.alerts), len(failing_sink.alerts))
        == (8, 3, 1),
        "severity and code routing preserved",
    )
    verification.expect(
        all(value not in repr(result) for value in SENSITIVE_VALUES),
        "routing result omits raw sink errors",
    )

    deduplicated_sink = RecordingSink()
    deduplicated = await OperationalAlertRouter(
        (AlertRoute(name="deduplicated", sink=deduplicated_sink),)
    ).route((*alerts, alerts[0]))
    verification.expect(
        deduplicated.alerts == 8 and deduplicated.delivered == 8,
        "duplicate fingerprints delivered once per routing pass",
    )
    return verification


def main() -> int:
    """Run the isolated operational-alert verifier."""
    _configure_stdout()
    try:
        verification = asyncio.run(verify())
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    print(
        "Operational alert verification passed: "
        f"{verification.checks}/{verification.checks} checks."
    )
    print("External network, PostgreSQL, Telegram, and AI calls: disabled.")
    return 0


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
                source_url="https://ggsel.example/private?token=must-not-leak",
                executed=True,
                result=MarketplaceRunResult(
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
                ),
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


def _dashboard(*, ambiguous: int = 2) -> DashboardSummaryRead:
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
        generated_content_awaiting_review=0,
        approved_content_awaiting_publication=0,
        publications_pending=0,
        publications_retryable=0,
        publications_permanently_failed=1,
        publications_ambiguous=ambiguous,
        publications_published=4,
        latest_event_activity_at=NOW,
        latest_publication_at=NOW,
    )


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")


if __name__ == "__main__":
    raise SystemExit(main())
