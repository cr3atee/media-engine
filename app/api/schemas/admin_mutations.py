from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.admin_actions import (
    AdminActionType,
    AdminResourceType,
    AmbiguousPublicationResolution,
)


def _nonempty_text(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("Value must not be blank.")
    return normalized


class ApproveContentRequest(BaseModel):
    """Input for approving one generated-content attempt."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=2000)


class RejectContentRequest(BaseModel):
    """Input for rejecting one generated-content attempt."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)

    _normalize_reason = field_validator("reason")(_nonempty_text)


class PublicationRetryRequest(BaseModel):
    """Input for explicitly retrying one known failed publication."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)

    _normalize_reason = field_validator("reason")(_nonempty_text)


class PublicationCancelRequest(BaseModel):
    """Input for cancelling publication work that has not become terminal."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)

    _normalize_reason = field_validator("reason")(_nonempty_text)


class ResolveAmbiguousPublicationRequest(BaseModel):
    """Input for an explicit operator decision on ambiguous delivery."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    resolution: AmbiguousPublicationResolution
    reason: str = Field(min_length=1, max_length=2000)
    external_message_id: str | None = Field(default=None, max_length=255)

    _normalize_reason = field_validator("reason")(_nonempty_text)

    @model_validator(mode="after")
    def validate_resolution_payload(self) -> Self:
        """Require a message ID only when delivery is confirmed."""
        if self.resolution is AmbiguousPublicationResolution.DELIVERED:
            if self.external_message_id is None:
                raise ValueError(
                    "Delivered resolution requires an external message ID."
                )
            self.external_message_id = _nonempty_text(self.external_message_id)
        elif self.external_message_id is not None:
            raise ValueError(
                "External message ID is valid only for delivered resolution."
            )
        return self


class AdminMutationResponse(BaseModel):
    """Stable public representation of an accepted admin command."""

    model_config = ConfigDict(extra="forbid")

    action_id: UUID
    action: AdminActionType
    resource_type: AdminResourceType
    resource_id: UUID
    previous_state: str
    resulting_state: str
    resulting_version: int
    request_id: str
    recorded_at: datetime
    replayed: bool
