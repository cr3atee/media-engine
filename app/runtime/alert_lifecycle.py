from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from app.runtime.alerts import AlertSeverity, OperationalAlert


class AlertLifecycleTransition(StrEnum):
    """Observable transition in the process-local lifecycle of an alert."""

    OPENED = "opened"
    REMINDER = "reminder"
    ESCALATED = "escalated"
    RESOLVED = "resolved"


@dataclass(slots=True, frozen=True, kw_only=True)
class AlertLifecyclePolicy:
    """Deterministic notification policy for repeatedly evaluated alerts."""

    reminder_interval: timedelta = timedelta(minutes=30)

    def __post_init__(self) -> None:
        if self.reminder_interval <= timedelta(0):
            raise ValueError("Alert reminder interval must be positive.")


@dataclass(slots=True, frozen=True, kw_only=True)
class AlertLifecycleNotification:
    """One safe lifecycle transition ready for an operations sink."""

    transition: AlertLifecycleTransition
    alert: OperationalAlert
    occurred_at: datetime
    first_seen_at: datetime
    last_seen_at: datetime
    occurrence_count: int
    acknowledged_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class AlertLifecycleResult:
    """Summary of one lifecycle reconciliation pass."""

    notifications: tuple[AlertLifecycleNotification, ...]
    active_alerts: tuple[OperationalAlert, ...]
    acknowledged_alerts: int
    suppressed_notifications: int


@dataclass(slots=True)
class _ActiveAlertState:
    alert: OperationalAlert
    first_seen_at: datetime
    last_seen_at: datetime
    last_notified_at: datetime
    occurrence_count: int = 1
    acknowledged_at: datetime | None = None


_SEVERITY_ORDER = {
    AlertSeverity.WARNING: 1,
    AlertSeverity.CRITICAL: 2,
}


class OperationalAlertLifecycle:
    """Track alert transitions and suppress duplicate notifications in-process.

    Stable fingerprints make emitted notifications suitable for additional
    cross-process deduplication by the configured production log collector.
    """

    def __init__(self, policy: AlertLifecyclePolicy | None = None) -> None:
        """Initialize an empty lifecycle with an explicit or default policy."""
        self._policy = policy or AlertLifecyclePolicy()
        self._states: dict[str, _ActiveAlertState] = {}

    def reconcile(
        self,
        alerts: Sequence[OperationalAlert],
        observed_at: datetime,
    ) -> AlertLifecycleResult:
        """Reconcile one complete snapshot of active alert conditions."""
        observed_at = _normalize_utc(observed_at, field_name="observed_at")
        current = _index_alerts(alerts)
        notifications: list[AlertLifecycleNotification] = []
        suppressed = 0

        for fingerprint in sorted(self._states.keys() - current.keys()):
            resolved_state = self._states.pop(fingerprint)
            _ensure_monotonic(observed_at, resolved_state.last_seen_at)
            notifications.append(
                _notification(
                    AlertLifecycleTransition.RESOLVED,
                    resolved_state,
                    observed_at,
                )
            )

        for fingerprint, alert in sorted(current.items()):
            active_state = self._states.get(fingerprint)
            if active_state is None:
                active_state = _ActiveAlertState(
                    alert=alert,
                    first_seen_at=observed_at,
                    last_seen_at=observed_at,
                    last_notified_at=observed_at,
                )
                self._states[fingerprint] = active_state
                notifications.append(
                    _notification(
                        AlertLifecycleTransition.OPENED,
                        active_state,
                        observed_at,
                    )
                )
                continue

            _ensure_monotonic(observed_at, active_state.last_seen_at)
            previous_severity = active_state.alert.severity
            active_state.alert = alert
            active_state.last_seen_at = observed_at
            active_state.occurrence_count += 1

            if _SEVERITY_ORDER[alert.severity] > _SEVERITY_ORDER[previous_severity]:
                active_state.acknowledged_at = None
                active_state.last_notified_at = observed_at
                notifications.append(
                    _notification(
                        AlertLifecycleTransition.ESCALATED,
                        active_state,
                        observed_at,
                    )
                )
            elif active_state.acknowledged_at is not None:
                suppressed += 1
            elif (
                observed_at - active_state.last_notified_at
                >= self._policy.reminder_interval
            ):
                active_state.last_notified_at = observed_at
                notifications.append(
                    _notification(
                        AlertLifecycleTransition.REMINDER,
                        active_state,
                        observed_at,
                    )
                )
            else:
                suppressed += 1

        return AlertLifecycleResult(
            notifications=tuple(
                sorted(
                    notifications,
                    key=lambda item: (item.transition.value, item.alert.fingerprint),
                )
            ),
            active_alerts=tuple(
                self._states[fingerprint].alert for fingerprint in sorted(self._states)
            ),
            acknowledged_alerts=sum(
                state.acknowledged_at is not None for state in self._states.values()
            ),
            suppressed_notifications=suppressed,
        )

    def acknowledge(self, fingerprint: str, acknowledged_at: datetime) -> bool:
        """Acknowledge an active alert and suppress reminders until escalation."""
        state = self._states.get(fingerprint)
        if state is None:
            return False
        acknowledged_at = _normalize_utc(
            acknowledged_at,
            field_name="acknowledged_at",
        )
        if acknowledged_at < state.first_seen_at:
            raise ValueError("Alert acknowledgement cannot predate first observation.")
        state.acknowledged_at = acknowledged_at
        return True

    def list_active(self) -> tuple[OperationalAlert, ...]:
        """Return the current active alerts in deterministic order."""
        return tuple(
            self._states[fingerprint].alert for fingerprint in sorted(self._states)
        )


def _notification(
    transition: AlertLifecycleTransition,
    state: _ActiveAlertState,
    occurred_at: datetime,
) -> AlertLifecycleNotification:
    return AlertLifecycleNotification(
        transition=transition,
        alert=state.alert,
        occurred_at=occurred_at,
        first_seen_at=state.first_seen_at,
        last_seen_at=state.last_seen_at,
        occurrence_count=state.occurrence_count,
        acknowledged_at=state.acknowledged_at,
    )


def _index_alerts(
    alerts: Sequence[OperationalAlert],
) -> dict[str, OperationalAlert]:
    indexed: dict[str, OperationalAlert] = {}
    for alert in alerts:
        existing = indexed.get(alert.fingerprint)
        if existing is not None and existing != alert:
            raise ValueError("Conflicting active alerts share one fingerprint.")
        indexed[alert.fingerprint] = alert
    return indexed


def _ensure_monotonic(observed_at: datetime, previous: datetime) -> None:
    if observed_at < previous:
        raise ValueError("Alert observations must be chronological.")


def _normalize_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware.")
    return value.astimezone(UTC)
