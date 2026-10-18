from __future__ import annotations

from typing import Protocol, cast

import structlog

from app.runtime.alert_lifecycle import AlertLifecycleNotification
from app.runtime.alerts import AlertSeverity, OperationalAlert


class _StructuredAlertLogger(Protocol):
    def warning(self, event: str, **event_fields: object) -> object:
        """Write a warning event."""

    def error(self, event: str, **event_fields: object) -> object:
        """Write an error event."""


class StructuredLoggingAlertSink:
    """Emit allowlisted operational alert fields through project logging.

    Raw summaries and exception text are intentionally omitted so credentials,
    source payloads, URLs, and provider responses cannot enter alert logs.
    """

    def __init__(self, logger: _StructuredAlertLogger | None = None) -> None:
        """Use the provided logger or the project's configured structlog logger."""
        self._logger = logger or cast(
            _StructuredAlertLogger,
            structlog.get_logger(__name__),
        )

    async def publish(self, alert: OperationalAlert) -> None:
        """Publish one active alert using only allowlisted structured fields."""
        self._emit("operational_alert", alert, {})

    async def publish_lifecycle(
        self,
        notification: AlertLifecycleNotification,
    ) -> None:
        """Publish one opened, reminder, escalation, or resolution transition."""
        self._emit(
            "operational_alert_lifecycle",
            notification.alert,
            {
                "alert_transition": notification.transition.value,
                "occurred_at": notification.occurred_at.isoformat(),
                "first_seen_at": notification.first_seen_at.isoformat(),
                "last_seen_at": notification.last_seen_at.isoformat(),
                "occurrence_count": notification.occurrence_count,
                "acknowledged": notification.acknowledged_at is not None,
            },
        )

    def _emit(
        self,
        event: str,
        alert: OperationalAlert,
        additional_fields: dict[str, object],
    ) -> None:
        fields: dict[str, object] = {
            "alert_code": alert.code,
            "alert_severity": alert.severity.value,
            "alert_fingerprint": alert.fingerprint,
            "observed_value": alert.observed_value,
            "threshold": alert.threshold,
            **additional_fields,
        }
        if alert.tenant_id is not None:
            fields["tenant_id"] = str(alert.tenant_id)
        if alert.integration_id is not None:
            fields["integration_id"] = str(alert.integration_id)
        if alert.marketplace is not None:
            fields["marketplace"] = alert.marketplace
        if alert.reason_code is not None:
            fields["reason_code"] = alert.reason_code

        if alert.severity is AlertSeverity.CRITICAL:
            self._logger.error(event, **fields)
        else:
            self._logger.warning(event, **fields)
