from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AliasChoices, Field, model_validator

from app.api.schemas.common import ApiModel, DateRangeParams, RelatedSummaryResponse
from app.domain.lifecycle import EventDisposition, ScoringStatus


class EventQueryParams(DateRangeParams):
    """Validated filters and ordering for the event list endpoint."""

    marketplace: str | None = Field(default=None, max_length=64)
    event_type: Literal["price_drop"] | None = None
    disposition: EventDisposition | None = None
    scoring_status: ScoringStatus | None = None
    content_generation_status: (
        Literal["pending", "in_progress", "generated", "failed", "abandoned"] | None
    ) = None
    review_status: Literal["not_required", "pending", "approved", "rejected"] | None = (
        None
    )
    publication_status: (
        Literal[
            "pending", "in_progress", "published", "failed", "ambiguous", "cancelled"
        ]
        | None
    ) = None
    min_score: int | None = Field(default=None, ge=0, le=100)
    external_id: str | None = Field(default=None, max_length=255)
    search: str | None = Field(
        default=None,
        max_length=200,
        validation_alias=AliasChoices("search", "q"),
    )
    canonical_product_id: UUID | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    detected_from: datetime | None = None
    detected_to: datetime | None = None
    has_content: bool | None = None
    has_publication: bool | None = None
    has_failure: bool | None = None
    ambiguous_only: bool = False
    limit: int | None = Field(default=None, ge=1, le=500)
    cursor: str | None = Field(default=None, max_length=2048)
    sort: Literal["detected_at", "created_at"] = "detected_at"
    direction: Literal["asc", "desc"] = "desc"

    @model_validator(mode="after")
    def validate_range(self) -> EventQueryParams:
        _validate_range(self.created_from, self.created_to, "created")
        _validate_range(self.detected_from, self.detected_to, "detected")
        return self


class SnapshotResponse(ApiModel):
    """Public representation of one snapshot identity."""

    marketplace: str
    external_id: str
    collected_at: datetime
    price: str
    currency: str


class PriceDropPayloadResponse(ApiModel):
    """Versioned public representation of a price-drop payload."""

    type: Literal["price_drop"]
    version: int = Field(ge=1)
    title: str | None
    url: str | None
    old_price: str
    new_price: str
    currency: str
    absolute_difference: str
    percentage: str
    previous_snapshot: SnapshotResponse
    current_snapshot: SnapshotResponse


class EventResponse(ApiModel):
    """Public event detail/list projection."""

    id: UUID
    identity_key: str
    identity_version: int = Field(ge=1)
    event_type: Literal["price_drop"]
    marketplace: str
    external_id: str
    canonical_product_id: UUID | None
    payload: PriceDropPayloadResponse
    occurred_at: datetime
    detected_at: datetime
    created_at: datetime
    disposition: str
    scoring_status: str
    score: int | None
    scoring_attempt_count: int = Field(ge=0)
    next_retry_at: datetime | None
    error_code: str | None
    error_summary: str | None
    version: int = Field(ge=1)
    content_summary: RelatedSummaryResponse
    publication_summary: RelatedSummaryResponse


def _validate_range(
    start: datetime | None,
    end: datetime | None,
    name: str,
) -> None:
    if start is not None and end is not None and start > end:
        raise ValueError(f"{name} range start must not be after its end.")
