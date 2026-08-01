from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.api.schemas.common import ApiModel, DateRangeParams


class PublicationQueryParams(DateRangeParams):
    """Validated filters and ordering for publications."""

    event_id: UUID | None = None
    content_id: UUID | None = None
    channel: str | None = Field(default=None, max_length=64)
    status: (
        Literal[
            "pending", "in_progress", "published", "failed", "ambiguous", "cancelled"
        ]
        | None
    ) = None
    retryable: bool | None = None
    permanent_failure: bool | None = None
    ambiguous_only: bool = False
    scheduled_from: datetime | None = None
    scheduled_to: datetime | None = None
    published_from: datetime | None = None
    published_to: datetime | None = None
    min_attempts: int | None = Field(default=None, ge=0)
    max_attempts: int | None = Field(default=None, ge=0)
    limit: int | None = Field(default=None, ge=1, le=500)
    cursor: str | None = Field(default=None, max_length=2048)
    sort: Literal["created_at"] = "created_at"
    direction: Literal["asc", "desc"] = "desc"

    @model_validator(mode="after")
    def validate_ranges(self) -> PublicationQueryParams:
        _validate_range(self.scheduled_from, self.scheduled_to, "scheduled")
        _validate_range(self.published_from, self.published_to, "published")
        if (
            self.min_attempts is not None
            and self.max_attempts is not None
            and self.min_attempts > self.max_attempts
        ):
            raise ValueError("Attempt range start must not be after its end.")
        return self


class PublicationResponse(ApiModel):
    """Public publication/delivery state projection."""

    id: UUID
    event_id: UUID
    content_id: UUID
    channel: str
    destination_reference: str
    status: str
    attempt_count: int = Field(ge=0)
    external_message_id: str | None
    scheduled_at: datetime | None
    next_retry_at: datetime | None
    published_at: datetime | None
    error_code: str | None
    error_summary: str | None
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=1)


def _validate_range(
    start: datetime | None,
    end: datetime | None,
    name: str,
) -> None:
    if start is not None and end is not None and start > end:
        raise ValueError(f"{name} range start must not be after its end.")
