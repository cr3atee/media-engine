from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from app.domain.marketplace import Marketplace
from app.repositories.queries.contracts import DashboardQueryRepository
from app.repositories.queries.models import DashboardSummaryRead, DashboardWindow
from app.repositories.queries.provider import (
    ReadRepositoryProvider,
    ReadRepositoryScopeFactory,
    create_memory_read_provider,
)
from app.runtime.alert_lifecycle import (
    AlertLifecycleNotification,
    OperationalAlertLifecycle,
)
from app.runtime.alert_monitor import RuntimeAlertMonitor
from app.services.marketplace_application_runner import MarketplaceRunResult
from app.services.marketplace_integration_execution import (
    MarketplaceIntegrationExecution,
    MarketplaceIntegrationExecutionBatch,
)

TENANT_ID = UUID("55000000-0000-4000-8000-000000000001")
INTEGRATION_ID = UUID("55000000-0000-4000-8000-000000000002")
NOW = datetime(2026, 10, 18, 10, 0, tzinfo=UTC)


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


class ToggleDashboardRepository(DashboardQueryRepository):
    def __init__(self, summary: DashboardSummaryRead) -> None:
        self.summary = summary
        self.fail = False

    async def get_summary(self, window: DashboardWindow) -> DashboardSummaryRead:
        if self.fail:
            raise RuntimeError("private database detail")
        return self.summary


class RecordingLifecycleSink:
    def __init__(self, *, fail: bool = False) -> None:
        self.notifications: list[AlertLifecycleNotification] = []
        self.fail = fail

    async def publish_lifecycle(
        self,
        notification: AlertLifecycleNotification,
    ) -> None:
        self.notifications.append(notification)
        if self.fail:
            raise OSError("private collector detail")


def test_monitor_reconciles_dashboard_alerts_without_false_resolution_on_read_error() -> (  # noqa: E501
    None
):
    dashboard = ToggleDashboardRepository(_dashboard(failed=2, exhausted=1))
    provider = create_memory_read_provider()
    provider = ReadRepositoryProvider(
        events=provider.events,
        content=provider.content,
        publications=provider.publications,
        dashboard=dashboard,
    )
    sink = RecordingLifecycleSink()
    monitor = RuntimeAlertMonitor(
        read_repository_scope_factory=_scope(provider),
        lifecycle=OperationalAlertLifecycle(),
        sink=sink,
        dashboard_window=timedelta(hours=24),
    )

    opened = run_async(monitor.evaluate(batch=_batch(), observed_at=NOW))
    repeated = run_async(
        monitor.evaluate(batch=None, observed_at=NOW + timedelta(minutes=5))
    )
    dashboard.fail = True
    unavailable = run_async(
        monitor.evaluate(batch=None, observed_at=NOW + timedelta(minutes=6))
    )
    dashboard.fail = False
    dashboard.summary = _dashboard(failed=0, exhausted=0)
    resolved = run_async(
        monitor.evaluate(batch=None, observed_at=NOW + timedelta(minutes=7))
    )

    assert opened.active_alerts == 2
    assert opened.notifications == 2
    assert opened.delivered == 2
    assert repeated.notifications == 0
    assert repeated.suppressed == 2
    assert unavailable.dashboard_error_code == "RuntimeError"
    assert unavailable.active_alerts == 2
    assert unavailable.notifications == 0
    assert resolved.active_alerts == 0
    assert resolved.notifications == 2
    assert {item.transition.value for item in sink.notifications} == {
        "opened",
        "resolved",
    }
    assert "private database detail" not in repr(unavailable)


def test_monitor_isolates_lifecycle_sink_failures() -> None:
    dashboard = ToggleDashboardRepository(_dashboard(failed=1, exhausted=1))
    provider = create_memory_read_provider()
    provider = ReadRepositoryProvider(
        events=provider.events,
        content=provider.content,
        publications=provider.publications,
        dashboard=dashboard,
    )
    monitor = RuntimeAlertMonitor(
        read_repository_scope_factory=_scope(provider),
        lifecycle=OperationalAlertLifecycle(),
        sink=RecordingLifecycleSink(fail=True),
        dashboard_window=timedelta(hours=24),
    )

    result = run_async(monitor.evaluate(batch=_batch(), observed_at=NOW))

    assert result.notifications == 2
    assert result.delivered == 0
    assert len(result.delivery_failures) == 2
    assert all(item.error_code == "OSError" for item in result.delivery_failures)
    assert "private collector detail" not in repr(result)


def _scope(provider: ReadRepositoryProvider) -> ReadRepositoryScopeFactory:
    @asynccontextmanager
    async def scope() -> AsyncIterator[ReadRepositoryProvider]:
        yield provider

    return scope


def _batch() -> MarketplaceIntegrationExecutionBatch:
    return MarketplaceIntegrationExecutionBatch(
        selected_integrations=1,
        executed_integrations=1,
        skipped_integrations=0,
        executions=(
            MarketplaceIntegrationExecution(
                integration_id=INTEGRATION_ID,
                tenant_id=TENANT_ID,
                marketplace=Marketplace.GGSEL.value,
                source_url="https://example.com/private",
                executed=True,
                result=MarketplaceRunResult(
                    marketplace=Marketplace.GGSEL,
                    offers_received=1,
                    offers_persisted=1,
                    comparison_results=0,
                    snapshots_created=1,
                    snapshots_persisted=1,
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
                    errors=(),
                    tenant_id=TENANT_ID,
                ),
            ),
        ),
    )


def _dashboard(*, failed: int, exhausted: int) -> DashboardSummaryRead:
    return DashboardSummaryRead(
        window=DashboardWindow(
            starts_at=NOW - timedelta(hours=24),
            ends_at=NOW,
            tenant_id=TENANT_ID,
        ),
        total_new_market_events=0,
        events_awaiting_scoring=0,
        scoring_failures=0,
        generated_content_pending=0,
        generated_content_failed=failed,
        generated_content_attempts_exhausted=exhausted,
        generated_content_awaiting_review=0,
        approved_content_awaiting_publication=0,
        publications_pending=0,
        publications_retryable=0,
        publications_permanently_failed=0,
        publications_ambiguous=0,
        publications_published=0,
        latest_event_activity_at=None,
        latest_publication_at=None,
    )
