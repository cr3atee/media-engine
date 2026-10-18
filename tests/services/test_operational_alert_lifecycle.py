from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from app.runtime.alert_lifecycle import (
    AlertLifecyclePolicy,
    AlertLifecycleTransition,
    OperationalAlertLifecycle,
)
from app.runtime.alert_sinks import StructuredLoggingAlertSink
from app.runtime.alerts import AlertSeverity, OperationalAlert

TENANT_ID = UUID("54000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 10, 18, 8, 0, tzinfo=UTC)


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


class RecordingLogger:
    def __init__(self) -> None:
        self.entries: list[tuple[str, str, dict[str, object]]] = []

    def warning(self, event: str, **event_fields: object) -> object:
        self.entries.append(("warning", event, event_fields))
        return None

    def error(self, event: str, **event_fields: object) -> object:
        self.entries.append(("error", event, event_fields))
        return None


def test_lifecycle_opens_suppresses_acknowledges_escalates_and_resolves() -> None:
    lifecycle = OperationalAlertLifecycle(
        AlertLifecyclePolicy(reminder_interval=timedelta(minutes=10))
    )
    warning = _alert(AlertSeverity.WARNING, observed_value=1)

    opened = lifecycle.reconcile((warning,), NOW)
    suppressed = lifecycle.reconcile((warning,), NOW + timedelta(minutes=5))
    acknowledged = lifecycle.acknowledge(
        warning.fingerprint,
        NOW + timedelta(minutes=6),
    )
    acknowledged_pass = lifecycle.reconcile(
        (warning,),
        NOW + timedelta(minutes=20),
    )
    critical = _alert(AlertSeverity.CRITICAL, observed_value=4)
    escalated = lifecycle.reconcile((critical,), NOW + timedelta(minutes=21))
    resolved = lifecycle.reconcile((), NOW + timedelta(minutes=22))
    reopened = lifecycle.reconcile((warning,), NOW + timedelta(minutes=23))

    assert [item.transition for item in opened.notifications] == [
        AlertLifecycleTransition.OPENED
    ]
    assert suppressed.notifications == ()
    assert suppressed.suppressed_notifications == 1
    assert acknowledged is True
    assert acknowledged_pass.notifications == ()
    assert acknowledged_pass.acknowledged_alerts == 1
    assert [item.transition for item in escalated.notifications] == [
        AlertLifecycleTransition.ESCALATED
    ]
    assert escalated.notifications[0].occurrence_count == 4
    assert escalated.acknowledged_alerts == 0
    assert [item.transition for item in resolved.notifications] == [
        AlertLifecycleTransition.RESOLVED
    ]
    assert resolved.active_alerts == ()
    assert [item.transition for item in reopened.notifications] == [
        AlertLifecycleTransition.OPENED
    ]


def test_lifecycle_emits_reminders_only_after_the_configured_window() -> None:
    lifecycle = OperationalAlertLifecycle(
        AlertLifecyclePolicy(reminder_interval=timedelta(minutes=10))
    )
    alert = _alert(AlertSeverity.WARNING, observed_value=1)

    lifecycle.reconcile((alert,), NOW)
    early = lifecycle.reconcile((alert,), NOW + timedelta(minutes=9))
    reminder = lifecycle.reconcile((alert,), NOW + timedelta(minutes=10))

    assert early.notifications == ()
    assert [item.transition for item in reminder.notifications] == [
        AlertLifecycleTransition.REMINDER
    ]
    assert reminder.notifications[0].occurrence_count == 3


def test_lifecycle_rejects_invalid_time_and_conflicting_fingerprints() -> None:
    lifecycle = OperationalAlertLifecycle()
    alert = _alert(AlertSeverity.WARNING, observed_value=1)
    conflict = _alert(AlertSeverity.WARNING, observed_value=2)

    with pytest.raises(ValueError, match="timezone-aware"):
        lifecycle.reconcile((alert,), datetime(2026, 10, 18, 8, 0))
    with pytest.raises(ValueError, match="Conflicting"):
        lifecycle.reconcile((alert, conflict), NOW)

    lifecycle.reconcile((alert,), NOW)
    with pytest.raises(ValueError, match="chronological"):
        lifecycle.reconcile((alert,), NOW - timedelta(seconds=1))
    assert lifecycle.acknowledge("0" * 64, NOW) is False


def test_structured_sink_uses_allowlisted_fields_and_severity() -> None:
    logger = RecordingLogger()
    sink = StructuredLoggingAlertSink(logger)
    warning = _alert(AlertSeverity.WARNING, observed_value=1)
    critical = _alert(AlertSeverity.CRITICAL, observed_value=4)
    lifecycle = OperationalAlertLifecycle()
    notification = lifecycle.reconcile((critical,), NOW).notifications[0]

    run_async(sink.publish(warning))
    run_async(sink.publish_lifecycle(notification))

    assert [entry[:2] for entry in logger.entries] == [
        ("warning", "operational_alert"),
        ("error", "operational_alert_lifecycle"),
    ]
    assert logger.entries[1][2]["alert_transition"] == "opened"
    assert logger.entries[1][2]["tenant_id"] == str(TENANT_ID)
    assert "must-not-enter-logs" not in repr(logger.entries)


def _alert(
    severity: AlertSeverity,
    *,
    observed_value: int,
) -> OperationalAlert:
    return OperationalAlert(
        code="content_generation_attempts_exhausted",
        severity=severity,
        summary="Sensitive must-not-enter-logs provider response.",
        observed_value=observed_value,
        threshold=1,
        tenant_id=TENANT_ID,
    )
