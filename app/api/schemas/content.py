from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AliasChoices, Field, model_validator

from app.api.schemas.common import ApiModel, DateRangeParams, RelatedSummaryResponse


class ContentQueryParams(DateRangeParams):
    """Validated filters and ordering for generated content."""

    event_id: UUID | None = None
    search: str | None = Field(
        default=None,
        max_length=200,
        validation_alias=AliasChoices("search", "q"),
    )
    generation_status: (
        Literal["pending", "in_progress", "generated", "failed", "abandoned"] | None
    ) = None
    review_status: Literal["not_required", "pending", "approved", "rejected"] | None = (
        None
    )
    attempt_number: int | None = Field(default=None, ge=1)
    created_from: datetime | None = None
    created_to: datetime | None = None
    completed_from: datetime | None = None
    completed_to: datetime | None = None
    has_publication: bool | None = None
    failed_only: bool = False
    limit: int | None = Field(default=None, ge=1, le=500)
    cursor: str | None = Field(default=None, max_length=2048)
    sort: Literal["created_at", "updated_at"] = "created_at"
    direction: Literal["asc", "desc"] = "desc"

    @model_validator(mode="after")
    def validate_range(self) -> ContentQueryParams:
        _validate_range(self.created_from, self.created_to, "created")
        _validate_range(self.completed_from, self.completed_to, "completed")
        return self


class ContentResponse(ApiModel):
    """Public generated-content attempt projection."""

    id: UUID
    event_id: UUID
    parent_content_id: UUID | None
    content_type: str
    language: str
    origin: str
    provider: str | None
    model: str | None
    prompt_version: str
    content_text: str | None
    generation_status: str
    review_status: str
    attempt_number: int = Field(ge=1)
    content_checksum: str | None
    next_retry_at: datetime | None
    error_code: str | None
    error_summary: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    version: int = Field(ge=1)
    publication_summary: RelatedSummaryResponse


def _validate_range(
    start: datetime | None,
    end: datetime | None,
    name: str,
) -> None:
    if start is not None and end is not None and start > end:
        raise ValueError(f"{name} range start must not be after its end.")
