from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from typing import Protocol
from uuid import UUID

from app.repositories.queries.models import DashboardSummaryRead
from app.services.marketplace_application_runner import MarketplaceRunResult
from app.services.marketplace_integration_execution import (
    MarketplaceIntegrationExecutionBatch,
)


class AlertSeverity(StrEnum):
    """Operational severity used independently from any delivery channel."""

    WARNING = "warning"
    CRITICAL = "critical"


_SEVERITY_ORDER = {
    AlertSeverity.WARNING: 1,
    AlertSeverity.CRITICAL: 2,
}


@dataclass(slots=True, frozen=True, kw_only=True)
class MarketplaceVolumeBaseline:
    """Explicit minimum source volume for one tenant integration."""

    tenant_id: UUID
    integration_id: UUID
    minimum_offers_received: int

    def __post_init__(self) -> None:
        if self.minimum_offers_received < 1:
            raise ValueError("Marketplace volume baseline must be positive.")


@dataclass(slots=True, frozen=True, kw_only=True)
class OperationalAlert:
    """Safe deterministic alert independent from a concrete notification sink."""

    code: str
    severity: AlertSeverity
    summary: str
    observed_value: int
    threshold: int
    tenant_id: UUID | None = None
    integration_id: UUID | None = None
    marketplace: str | None = None
    reason_code: str | None = None
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        code = _normalize_code(self.code, field_name="alert code")
        summary = _normalize_text(
            self.summary,
            field_name="alert summary",
            maximum_length=300,
        )
        marketplace = _optional_code(self.marketplace, field_name="marketplace")
        reason_code = _optional_code(self.reason_code, field_name="reason code")
        if self.observed_value < 0 or self.threshold < 0:
            raise ValueError("Alert values must not be negative.")
        if self.integration_id is not None and self.tenant_id is None:
            raise ValueError("Integration-scoped alerts require a tenant ID.")

        identity = "|".join(
            (
                code,
                str(self.tenant_id or ""),
                str(self.integration_id or ""),
                marketplace or "",
                reason_code or "",
            )
        )
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "severity", AlertSeverity(self.severity))
        object.__setattr__(self, "summary", summary)
        object.__setattr__(self, "marketplace", marketplace)
        object.__setattr__(self, "reason_code", reason_code)
        object.__setattr__(
            self,
            "fingerprint",
            sha256(identity.encode("utf-8")).hexdigest(),
        )


class OperationalAlertEngine:
    """Evaluate current runtime/read-model state with explicit thresholds."""

    def evaluate(
        self,
        *,
        batch: MarketplaceIntegrationExecutionBatch | None = None,
        dashboard: DashboardSummaryRead | None = None,
        volume_baselines: Sequence[MarketplaceVolumeBaseline] = (),
    ) -> tuple[OperationalAlert, ...]:
        """Return deterministic active alerts for supplied observations."""
        baselines = _index_baselines(volume_baselines)
        alerts: list[OperationalAlert] = []
        if batch is not None:
            alerts.extend(self._evaluate_marketplace_batch(batch, baselines))
        if dashboard is not None:
            alerts.extend(self._evaluate_dashboard(dashboard))
        return tuple(
            sorted(
                alerts,
                key=lambda alert: (
                    -_SEVERITY_ORDER[alert.severity],
                    alert.code,
                    alert.fingerprint,
                ),
            )
        )

    def _evaluate_marketplace_batch(
        self,
        batch: MarketplaceIntegrationExecutionBatch,
        baselines: dict[tuple[UUID, UUID], MarketplaceVolumeBaseline],
    ) -> list[OperationalAlert]:
        alerts: list[OperationalAlert] = []
        for execution in batch.executions:
            if not execution.executed:
                alerts.append(
                    OperationalAlert(
                        code="marketplace_polling_skipped",
                        severity=AlertSeverity.WARNING,
                        summary="Marketplace integration polling was skipped.",
                        observed_value=1,
                        threshold=1,
                        reason_code=execution.skipped_reason,
                        tenant_id=execution.tenant_id,
                        integration_id=execution.integration_id,
                        marketplace=execution.marketplace,
                    )
                )
                continue
            if not execution.succeeded:
                alerts.append(
                    OperationalAlert(
                        code="marketplace_polling_failed",
                        severity=AlertSeverity.CRITICAL,
                        summary="Marketplace integration polling failed.",
                        observed_value=1,
                        threshold=1,
                        reason_code=execution.error_code,
                        tenant_id=execution.tenant_id,
                        integration_id=execution.integration_id,
                        marketplace=execution.marketplace,
                    )
                )
                continue

            result = execution.result
            if not isinstance(result, MarketplaceRunResult):
                continue
            if result.errors:
                alerts.append(
                    OperationalAlert(
                        code="marketplace_processing_errors",
                        severity=AlertSeverity.WARNING,
                        summary="Marketplace polling completed with processing errors.",
                        observed_value=len(result.errors),
                        threshold=1,
                        tenant_id=execution.tenant_id,
                        integration_id=execution.integration_id,
                        marketplace=execution.marketplace,
                    )
                )
            baseline = baselines.get((execution.tenant_id, execution.integration_id))
            if (
                baseline is not None
                and result.offers_received < baseline.minimum_offers_received
            ):
                alerts.append(
                    OperationalAlert(
                        code="marketplace_source_volume_below_baseline",
                        severity=AlertSeverity.WARNING,
                        summary=(
                            "Marketplace source volume is below its explicit baseline."
                        ),
                        observed_value=result.offers_received,
                        threshold=baseline.minimum_offers_received,
                        tenant_id=execution.tenant_id,
                        integration_id=execution.integration_id,
                        marketplace=execution.marketplace,
                    )
                )
        return alerts

    def _evaluate_dashboard(
        self,
        dashboard: DashboardSummaryRead,
    ) -> list[OperationalAlert]:
        tenant_id = dashboard.window.tenant_id
        conditions = (
            (
                "event_scoring_failed",
                AlertSeverity.WARNING,
                "Market event scoring failures are present.",
                dashboard.scoring_failures,
            ),
            (
                "content_generation_failed",
                AlertSeverity.WARNING,
                "Content generation failures are present.",
                dashboard.generated_content_failed,
            ),
            (
                "content_generation_attempts_exhausted",
                AlertSeverity.CRITICAL,
                "Content generation attempts are exhausted.",
                dashboard.generated_content_attempts_exhausted,
            ),
            (
                "publication_permanently_failed",
                AlertSeverity.CRITICAL,
                "Permanently failed publications require operator attention.",
                dashboard.publications_permanently_failed,
            ),
            (
                "publication_ambiguous",
                AlertSeverity.CRITICAL,
                "Ambiguous publications require operator resolution.",
                dashboard.publications_ambiguous,
            ),
        )
        return [
            OperationalAlert(
                code=code,
                severity=severity,
                summary=summary,
                observed_value=value,
                threshold=1,
                tenant_id=tenant_id,
            )
            for code, severity, summary, value in conditions
            if value > 0
        ]


class AlertSink(Protocol):
    """Delivery-neutral destination for one safe operational alert."""

    async def publish(self, alert: OperationalAlert) -> None:
        """Publish one alert or raise when delivery fails."""


@dataclass(slots=True, frozen=True, kw_only=True)
class AlertRoute:
    """Route filter paired with one caller-owned alert sink."""

    name: str
    sink: AlertSink
    minimum_severity: AlertSeverity = AlertSeverity.WARNING
    codes: frozenset[str] | None = None

    def __post_init__(self) -> None:
        name = _normalize_text(self.name, field_name="route name", maximum_length=100)
        codes = (
            frozenset(
                _normalize_code(code, field_name="route alert code")
                for code in self.codes
            )
            if self.codes is not None
            else None
        )
        object.__setattr__(self, "name", name)
        object.__setattr__(
            self,
            "minimum_severity",
            AlertSeverity(self.minimum_severity),
        )
        object.__setattr__(self, "codes", codes)

    def accepts(self, alert: OperationalAlert) -> bool:
        """Return whether this route should receive the alert."""
        severity_matches = (
            _SEVERITY_ORDER[alert.severity] >= _SEVERITY_ORDER[self.minimum_severity]
        )
        code_matches = self.codes is None or alert.code in self.codes
        return severity_matches and code_matches


@dataclass(slots=True, frozen=True)
class AlertRouteFailure:
    """Safe failed-delivery evidence without exception text."""

    route_name: str
    alert_fingerprint: str
    error_code: str


@dataclass(slots=True, frozen=True)
class AlertRoutingResult:
    """Deterministic summary of one routing pass."""

    alerts: int
    attempted_deliveries: int
    delivered: int
    failures: tuple[AlertRouteFailure, ...]


class OperationalAlertRouter:
    """Route alerts to independent sinks while isolating delivery failures."""

    def __init__(self, routes: Sequence[AlertRoute]) -> None:
        """Initialize uniquely named routes in deterministic order."""
        by_name = {route.name: route for route in routes}
        if len(by_name) != len(routes):
            raise ValueError("Operational alert route names must be unique.")
        self._routes = tuple(sorted(routes, key=lambda route: route.name))

    async def route(
        self,
        alerts: Sequence[OperationalAlert],
    ) -> AlertRoutingResult:
        """Deliver matching alerts without allowing one sink to stop another."""
        unique_alerts = _unique_alerts(alerts)
        attempted = 0
        delivered = 0
        failures: list[AlertRouteFailure] = []
        for alert in unique_alerts:
            for route in self._routes:
                if not route.accepts(alert):
                    continue
                attempted += 1
                try:
                    await route.sink.publish(alert)
                except Exception as error:
                    failures.append(
                        AlertRouteFailure(
                            route_name=route.name,
                            alert_fingerprint=alert.fingerprint,
                            error_code=type(error).__name__,
                        )
                    )
                else:
                    delivered += 1
        return AlertRoutingResult(
            alerts=len(unique_alerts),
            attempted_deliveries=attempted,
            delivered=delivered,
            failures=tuple(failures),
        )


def _index_baselines(
    baselines: Sequence[MarketplaceVolumeBaseline],
) -> dict[tuple[UUID, UUID], MarketplaceVolumeBaseline]:
    indexed: dict[tuple[UUID, UUID], MarketplaceVolumeBaseline] = {}
    for baseline in baselines:
        identity = (baseline.tenant_id, baseline.integration_id)
        if identity in indexed:
            raise ValueError("Marketplace volume baselines must be unique.")
        indexed[identity] = baseline
    return indexed


def _unique_alerts(
    alerts: Sequence[OperationalAlert],
) -> tuple[OperationalAlert, ...]:
    unique: dict[str, OperationalAlert] = {}
    for alert in alerts:
        existing = unique.get(alert.fingerprint)
        if existing is not None and existing != alert:
            raise ValueError("Conflicting alerts share one fingerprint.")
        unique[alert.fingerprint] = alert
    return tuple(
        sorted(
            unique.values(),
            key=lambda alert: (
                -_SEVERITY_ORDER[alert.severity],
                alert.code,
                alert.fingerprint,
            ),
        )
    )


def _optional_code(value: str | None, *, field_name: str) -> str | None:
    return _normalize_code(value, field_name=field_name) if value is not None else None


def _normalize_code(value: str, *, field_name: str) -> str:
    normalized = value.strip().lower()
    if not normalized or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789_.-"
        for character in normalized
    ):
        raise ValueError(f"{field_name} must be a non-empty safe code.")
    return normalized


def _normalize_text(value: str, *, field_name: str, maximum_length: int) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{field_name} must not be empty.")
    if len(normalized) > maximum_length:
        raise ValueError(f"{field_name} must not exceed {maximum_length} characters.")
    return normalized
