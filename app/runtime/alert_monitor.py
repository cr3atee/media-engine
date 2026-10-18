from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from app.domain.identity import normalize_utc
from app.repositories.queries.models import DashboardWindow
from app.repositories.queries.provider import ReadRepositoryScopeFactory
from app.runtime.alert_lifecycle import (
    AlertLifecycleNotification,
    OperationalAlertLifecycle,
)
from app.runtime.alerts import OperationalAlertEngine
from app.services.marketplace_integration_execution import (
    MarketplaceIntegrationExecutionBatch,
)


class AlertLifecycleSink(Protocol):
    """Destination for one lifecycle-aware operational notification."""

    async def publish_lifecycle(
        self,
        notification: AlertLifecycleNotification,
    ) -> None:
        """Publish one lifecycle notification or raise on failure."""


@dataclass(slots=True, frozen=True)
class AlertLifecycleDeliveryFailure:
    """Sanitized evidence that one lifecycle notification was not delivered."""

    alert_fingerprint: str
    transition: str
    error_code: str


@dataclass(slots=True, frozen=True)
class RuntimeAlertEvaluationResult:
    """Safe summary of one runtime alert evaluation and delivery pass."""

    active_alerts: int
    dashboard_tenants: int
    notifications: int
    delivered: int
    suppressed: int
    delivery_failures: tuple[AlertLifecycleDeliveryFailure, ...]
    dashboard_error_code: str | None = None


class RuntimeAlertMonitor:
    """Orchestrate read-side alert evaluation, lifecycle, and delivery only."""

    def __init__(
        self,
        *,
        read_repository_scope_factory: ReadRepositoryScopeFactory,
        lifecycle: OperationalAlertLifecycle,
        sink: AlertLifecycleSink,
        dashboard_window: timedelta,
        engine: OperationalAlertEngine | None = None,
    ) -> None:
        """Bind existing alert components to a bounded dashboard read scope."""
        if dashboard_window <= timedelta(0):
            raise ValueError("Alert dashboard window must be positive.")
        self._read_repository_scope_factory = read_repository_scope_factory
        self._lifecycle = lifecycle
        self._sink = sink
        self._dashboard_window = dashboard_window
        self._engine = engine or OperationalAlertEngine()
        self._known_tenant_ids: set[UUID] = set()

    async def evaluate(
        self,
        *,
        batch: MarketplaceIntegrationExecutionBatch | None,
        observed_at: datetime,
    ) -> RuntimeAlertEvaluationResult:
        """Evaluate current durable/runtime state without changing either one."""
        observed_at = normalize_utc(observed_at, field_name="observed_at")
        alerts = list(self._engine.evaluate(batch=batch))
        self._known_tenant_ids.update(_tenant_ids(batch))
        tenant_ids = tuple(sorted(self._known_tenant_ids, key=str))
        dashboard_error_code: str | None = None
        dashboards_read = 0

        if tenant_ids:
            try:
                async with self._read_repository_scope_factory() as repositories:
                    for tenant_id in tenant_ids:
                        dashboard = await repositories.dashboard.get_summary(
                            DashboardWindow(
                                starts_at=observed_at - self._dashboard_window,
                                ends_at=observed_at,
                                tenant_id=tenant_id,
                            )
                        )
                        alerts.extend(self._engine.evaluate(dashboard=dashboard))
                        dashboards_read += 1
            except Exception as error:
                dashboard_error_code = type(error).__name__

        if dashboard_error_code is not None:
            return RuntimeAlertEvaluationResult(
                active_alerts=len(self._lifecycle.list_active()),
                dashboard_tenants=dashboards_read,
                notifications=0,
                delivered=0,
                suppressed=0,
                delivery_failures=(),
                dashboard_error_code=dashboard_error_code,
            )

        lifecycle_result = self._lifecycle.reconcile(alerts, observed_at)
        delivered = 0
        failures: list[AlertLifecycleDeliveryFailure] = []
        for notification in lifecycle_result.notifications:
            try:
                await self._sink.publish_lifecycle(notification)
            except Exception as error:
                failures.append(
                    AlertLifecycleDeliveryFailure(
                        alert_fingerprint=notification.alert.fingerprint,
                        transition=notification.transition.value,
                        error_code=type(error).__name__,
                    )
                )
            else:
                delivered += 1

        return RuntimeAlertEvaluationResult(
            active_alerts=len(lifecycle_result.active_alerts),
            dashboard_tenants=dashboards_read,
            notifications=len(lifecycle_result.notifications),
            delivered=delivered,
            suppressed=lifecycle_result.suppressed_notifications,
            delivery_failures=tuple(failures),
            dashboard_error_code=dashboard_error_code,
        )


def _tenant_ids(
    batch: MarketplaceIntegrationExecutionBatch | None,
) -> Sequence[UUID]:
    if batch is None:
        return ()
    return tuple(
        sorted(
            {execution.tenant_id for execution in batch.executions},
            key=str,
        )
    )
