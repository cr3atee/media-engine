from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.api.schemas.common import ApiModel, utc_datetime
from app.repositories.queries.models import DashboardWindow

MAX_DASHBOARD_RANGE = timedelta(days=31)


class DashboardQueryParams(ApiModel):
    """Validated UTC time window for the operational dashboard summary."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: datetime | None = Field(
        default=None,
        alias="from",
        description="Inclusive UTC window start.",
    )
    to: datetime | None = Field(
        default=None,
        description="Exclusive UTC window end.",
    )

    @field_validator("from_", "to", mode="after")
    @classmethod
    def normalize_date(cls, value: datetime | None) -> datetime | None:
        """Require aware timestamps and normalize them to UTC."""
        return utc_datetime(value) if value is not None else None

    @model_validator(mode="after")
    def validate_explicit_range(self) -> DashboardQueryParams:
        """Reject reversed explicit time windows."""
        if self.from_ is not None and self.to is not None and self.from_ > self.to:
            raise ValueError("Dashboard range start must not be after its end.")
        return self

    def window(self, *, now: datetime | None = None) -> DashboardWindow:
        """Return a bounded `[from, to)` UTC dashboard window."""
        ends_at = self.to or (now or datetime.now(UTC))
        starts_at = self.from_ or (ends_at - timedelta(hours=24))
        if starts_at > ends_at:
            raise ValueError("Dashboard range start must not be after its end.")
        if ends_at - starts_at > MAX_DASHBOARD_RANGE:
            raise ValueError("Dashboard range must not exceed 31 days.")
        return DashboardWindow(starts_at=starts_at, ends_at=ends_at)


class DashboardWindowResponse(ApiModel):
    """Public representation of the bounded dashboard window."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: datetime = Field(alias="from")
    to: datetime
    boundary: str


class DashboardSummaryResponse(ApiModel):
    """Operational dashboard counters derived from durable current state."""

    window: DashboardWindowResponse
    total_new_market_events: int = Field(ge=0)
    events_awaiting_scoring: int = Field(ge=0)
    scoring_failures: int = Field(ge=0)
    generated_content_pending: int = Field(ge=0)
    generated_content_failed: int = Field(ge=0)
    generated_content_awaiting_review: int = Field(ge=0)
    approved_content_awaiting_publication: int = Field(ge=0)
    publications_pending: int = Field(ge=0)
    publications_retryable: int = Field(ge=0)
    publications_permanently_failed: int = Field(ge=0)
    publications_ambiguous: int = Field(ge=0)
    publications_published: int = Field(ge=0)
    latest_event_activity_at: datetime | None
    latest_publication_at: datetime | None
