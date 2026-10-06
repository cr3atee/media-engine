from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from app.domain.identity import normalize_utc


class MarketplacePollingRunStatus(StrEnum):
    """Terminal outcome retained for one marketplace integration run."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(slots=True, frozen=True, kw_only=True)
class MarketplacePollingRun:
    """Immutable, tenant-owned operational record for one polling attempt."""

    id: UUID
    tenant_id: UUID
    integration_id: UUID
    marketplace: str
    status: MarketplacePollingRunStatus
    started_at: datetime
    finished_at: datetime
    offers_received: int | None = None
    offers_persisted: int | None = None
    snapshots_created: int | None = None
    snapshots_persisted: int | None = None
    price_changes_detected: int | None = None
    events_created: int | None = None
    processing_error_count: int | None = None
    skipped_reason: str | None = None
    error_code: str | None = None
    error_summary: str | None = None

    def __post_init__(self) -> None:
        marketplace = _required_text(
            self.marketplace,
            field_name="marketplace",
            maximum_length=64,
        ).lower()
        started_at = normalize_utc(self.started_at, field_name="started_at")
        finished_at = normalize_utc(self.finished_at, field_name="finished_at")
        if finished_at < started_at:
            raise ValueError("Polling run must not finish before it starts.")

        status = MarketplacePollingRunStatus(self.status)
        skipped_reason = _optional_text(
            self.skipped_reason,
            field_name="skipped_reason",
            maximum_length=128,
        )
        error_code = _optional_text(
            self.error_code,
            field_name="error_code",
            maximum_length=128,
        )
        error_summary = _optional_text(
            self.error_summary,
            field_name="error_summary",
            maximum_length=2000,
        )
        _validate_outcome(status, skipped_reason, error_code, error_summary)

        for field_name in _COUNT_FIELDS:
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ValueError(f"{field_name} must not be negative.")

        object.__setattr__(self, "marketplace", marketplace)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "finished_at", finished_at)
        object.__setattr__(self, "skipped_reason", skipped_reason)
        object.__setattr__(self, "error_code", error_code)
        object.__setattr__(self, "error_summary", error_summary)

    @property
    def duration(self) -> timedelta:
        """Return the measured wall-clock duration of the attempt."""
        return self.finished_at - self.started_at


_COUNT_FIELDS = (
    "offers_received",
    "offers_persisted",
    "snapshots_created",
    "snapshots_persisted",
    "price_changes_detected",
    "events_created",
    "processing_error_count",
)


def _validate_outcome(
    status: MarketplacePollingRunStatus,
    skipped_reason: str | None,
    error_code: str | None,
    error_summary: str | None,
) -> None:
    if status is MarketplacePollingRunStatus.SKIPPED:
        has_error = error_code is not None or error_summary is not None
        if skipped_reason is None or has_error:
            raise ValueError("Skipped polling runs require only a skipped reason.")
        return
    if skipped_reason is not None:
        raise ValueError("Executed polling runs must not contain a skipped reason.")
    if status is MarketplacePollingRunStatus.FAILED:
        if error_code is None or error_summary is None:
            raise ValueError("Failed polling runs require safe error metadata.")
        return
    if error_code is not None or error_summary is not None:
        raise ValueError("Successful polling runs must not contain error metadata.")


def _optional_text(
    value: str | None,
    *,
    field_name: str,
    maximum_length: int,
) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name=field_name, maximum_length=maximum_length)


def _required_text(value: str, *, field_name: str, maximum_length: int) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{field_name} must not be empty.")
    if len(normalized) > maximum_length:
        raise ValueError(f"{field_name} must not exceed {maximum_length} characters.")
    return normalized
