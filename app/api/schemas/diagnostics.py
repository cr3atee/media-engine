"""Public schemas for safe frontend reports and admin incident reads."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.diagnostics import DiagnosticSeverity, DiagnosticSource


class FrontendDiagnosticRequest(BaseModel):
    """Strict allowlist that deliberately excludes messages, stacks and URLs."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["error", "unhandled_rejection", "request_failure"]
    page: Literal["catalog", "review", "not_found"]
    component: Literal["shell", "catalog", "review", "access", "network"]
    action: Literal["render", "load", "submit", "navigation", "unknown"]
    request_id: str = Field(
        default="unavailable",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )


class DiagnosticAcceptedResponse(BaseModel):
    """Stable acknowledgement without exposing aggregate details."""

    incident_id: UUID
    status: Literal["accepted"] = "accepted"


class DiagnosticIncidentResponse(BaseModel):
    """Sanitized incident projection available only to product admins."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    fingerprint: str
    source: DiagnosticSource
    severity: DiagnosticSeverity
    code: str
    component: str
    action: str
    route: str
    method: str
    status_code: int | None
    tenant_id: UUID | None
    user_id: UUID | None
    error_type: str | None
    environment: str
    release: str
    first_request_id: str
    last_request_id: str
    stack_frames: tuple[str, ...]
    first_seen_at: datetime
    last_seen_at: datetime
    occurrence_count: int


class DiagnosticIncidentPageResponse(BaseModel):
    """Bounded offset page for the product administration console."""

    items: list[DiagnosticIncidentResponse]
    total: int
    limit: int
    offset: int
