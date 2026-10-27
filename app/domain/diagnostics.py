"""Sanitized diagnostic incidents safe for durable operational storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.identity import normalize_utc, validate_sha256


class DiagnosticSource(StrEnum):
    """Trusted origin assigned by the backend, never by report payloads."""

    BACKEND = "backend"
    FRONTEND = "frontend"


class DiagnosticSeverity(StrEnum):
    """Small stable severity vocabulary used by storage and filters."""

    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True, kw_only=True)
class DiagnosticIncident:
    """Deduplicated incident containing metadata only, never request secrets."""

    id: UUID
    fingerprint: str
    source: DiagnosticSource
    severity: DiagnosticSeverity
    code: str
    component: str
    action: str
    route: str
    method: str
    environment: str
    release: str
    first_request_id: str
    last_request_id: str
    first_seen_at: datetime
    last_seen_at: datetime
    occurrence_count: int = 1
    status_code: int | None = None
    tenant_id: UUID | None = None
    user_id: UUID | None = None
    error_type: str | None = None
    stack_frames: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Normalize bounded fields and reject unsafe or invalid aggregates."""
        validate_sha256(self.fingerprint, field_name="Diagnostic fingerprint")
        normalized = {
            "code": _required_text(self.code, "code", 64),
            "component": _required_text(self.component, "component", 64),
            "action": _required_text(self.action, "action", 64),
            "route": _required_text(self.route, "route", 255),
            "method": _required_text(self.method, "method", 16).upper(),
            "environment": _required_text(self.environment, "environment", 64),
            "release": _required_text(self.release, "release", 128),
            "first_request_id": _required_text(
                self.first_request_id, "first_request_id", 128
            ),
            "last_request_id": _required_text(
                self.last_request_id, "last_request_id", 128
            ),
        }
        if "?" in normalized["route"]:
            raise ValueError("Diagnostic route must not contain a query string.")
        error_type = _optional_text(self.error_type, "error_type", 128)
        first_seen_at = normalize_utc(self.first_seen_at, field_name="first_seen_at")
        last_seen_at = normalize_utc(self.last_seen_at, field_name="last_seen_at")
        if last_seen_at < first_seen_at:
            raise ValueError(
                "Diagnostic last-seen time cannot predate first-seen time."
            )
        if self.occurrence_count < 1:
            raise ValueError("Diagnostic occurrence count must be positive.")
        if self.status_code is not None and not 100 <= self.status_code <= 599:
            raise ValueError("Diagnostic status code must be a valid HTTP status.")
        if len(self.stack_frames) > 20:
            raise ValueError("Diagnostic stack summary cannot exceed 20 frames.")
        frames = tuple(
            _required_text(frame, "stack_frame", 255) for frame in self.stack_frames
        )
        for field_name, value in normalized.items():
            object.__setattr__(self, field_name, value)
        object.__setattr__(self, "error_type", error_type)
        object.__setattr__(self, "first_seen_at", first_seen_at)
        object.__setattr__(self, "last_seen_at", last_seen_at)
        object.__setattr__(self, "stack_frames", frames)


def _required_text(value: str, field_name: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(
            f"Diagnostic {field_name} must contain 1-{maximum} characters."
        )
    return normalized


def _optional_text(value: str | None, field_name: str, maximum: int) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name, maximum)
