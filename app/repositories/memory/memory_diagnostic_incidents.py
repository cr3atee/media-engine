"""In-memory diagnostic repository for tests and local demos."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from uuid import UUID

from app.domain.diagnostics import (
    DiagnosticIncident,
    DiagnosticSeverity,
    DiagnosticSource,
)
from app.repositories.diagnostic_incidents import DiagnosticIncidentRepository


class MemoryDiagnosticIncidentRepository(DiagnosticIncidentRepository):
    """Preserve PostgreSQL-equivalent deduplication and ordering in memory."""

    def __init__(self) -> None:
        self._incidents: dict[UUID, DiagnosticIncident] = {}
        self._ids_by_fingerprint: dict[str, UUID] = {}

    async def record(self, incident: DiagnosticIncident) -> DiagnosticIncident:
        """Insert a first occurrence or update the existing aggregate."""
        existing_id = self._ids_by_fingerprint.get(incident.fingerprint)
        if existing_id is None:
            self._incidents[incident.id] = incident
            self._ids_by_fingerprint[incident.fingerprint] = incident.id
            return incident
        existing = self._incidents[existing_id]
        updated = replace(
            existing,
            last_seen_at=max(existing.last_seen_at, incident.last_seen_at),
            last_request_id=incident.last_request_id,
            occurrence_count=existing.occurrence_count + incident.occurrence_count,
            user_id=existing.user_id or incident.user_id,
            tenant_id=existing.tenant_id or incident.tenant_id,
            stack_frames=incident.stack_frames or existing.stack_frames,
        )
        self._incidents[existing_id] = updated
        return updated

    async def get_by_id(self, incident_id: UUID) -> DiagnosticIncident | None:
        """Return one incident by identifier."""
        return self._incidents.get(incident_id)

    async def list_recent(
        self,
        *,
        source: DiagnosticSource | None = None,
        severity: DiagnosticSeverity | None = None,
        component: str | None = None,
        environment: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[tuple[DiagnosticIncident, ...], int]:
        """Apply exact filters and deterministic newest-first pagination."""
        _validate_page(limit, offset)
        matching = [
            incident
            for incident in self._incidents.values()
            if (source is None or incident.source is source)
            and (severity is None or incident.severity is severity)
            and (component is None or incident.component == component)
            and (environment is None or incident.environment == environment)
        ]
        matching.sort(key=lambda item: (item.last_seen_at, item.id.hex), reverse=True)
        return tuple(matching[offset : offset + limit]), len(matching)

    async def delete_last_seen_before(self, cutoff: datetime) -> int:
        """Remove expired aggregates while keeping the fingerprint index aligned."""
        expired = tuple(
            incident_id
            for incident_id, incident in self._incidents.items()
            if incident.last_seen_at < cutoff
        )
        for incident_id in expired:
            incident = self._incidents.pop(incident_id)
            self._ids_by_fingerprint.pop(incident.fingerprint, None)
        return len(expired)


def _validate_page(limit: int, offset: int) -> None:
    if not 1 <= limit <= 100:
        raise ValueError("Diagnostic page limit must be between 1 and 100.")
    if offset < 0:
        raise ValueError("Diagnostic page offset cannot be negative.")
