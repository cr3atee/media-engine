from __future__ import annotations

from datetime import UTC, datetime
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

TResponse = TypeVar("TResponse")


class ApiModel(BaseModel):
    """Base API model that rejects undocumented fields."""

    model_config = ConfigDict(extra="forbid")


class PageResponse[TResponse](ApiModel):
    """Stable keyset page envelope."""

    items: list[TResponse]
    next_cursor: str | None
    page_size: int = Field(ge=1)


class RelatedSummaryResponse(ApiModel):
    """Compact related-resource status summary."""

    count: int = Field(ge=0)
    statuses: list[str]


def utc_datetime(value: datetime) -> datetime:
    """Require an aware timestamp and normalize it to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must include a timezone.")
    return value.astimezone(UTC)


class DateRangeParams(ApiModel):
    """Reusable aware UTC date-range validation."""

    @field_validator(
        "created_from",
        "created_to",
        "detected_from",
        "detected_to",
        "completed_from",
        "completed_to",
        "scheduled_from",
        "scheduled_to",
        "published_from",
        "published_to",
        mode="after",
        check_fields=False,
    )
    @classmethod
    def normalize_date(cls, value: datetime | None) -> datetime | None:
        return utc_datetime(value) if value is not None else None
