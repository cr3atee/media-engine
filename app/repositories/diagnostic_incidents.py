"""Persistence contract for sanitized operational incidents."""

from __future__ import annotations

from abc import abstractmethod
from datetime import datetime
from uuid import UUID

from app.domain.diagnostics import (
    DiagnosticIncident,
    DiagnosticSeverity,
    DiagnosticSource,
)
from app.repositories.base import BaseRepository


class DiagnosticIncidentRepository(BaseRepository):
    """Store deduplicated diagnostics independently from business data."""

    @abstractmethod
    async def record(self, incident: DiagnosticIncident) -> DiagnosticIncident:
        """Insert or aggregate one occurrence by deterministic fingerprint."""

    @abstractmethod
    async def get_by_id(self, incident_id: UUID) -> DiagnosticIncident | None:
        """Return one incident by its stable identifier."""

    @abstractmethod
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
        """Return a bounded newest-first page and total matching count."""

    @abstractmethod
    async def delete_last_seen_before(self, cutoff: datetime) -> int:
        """Delete aggregates outside the configured retention window."""
