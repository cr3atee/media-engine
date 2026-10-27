"""PostgreSQL persistence for sanitized diagnostic incidents."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.diagnostics import (
    DiagnosticIncident,
    DiagnosticSeverity,
    DiagnosticSource,
)
from app.models.diagnostic_incident_record import DiagnosticIncidentRecord
from app.repositories.diagnostic_incidents import DiagnosticIncidentRepository


class PostgresDiagnosticIncidentRepository(DiagnosticIncidentRepository):
    """Aggregate concurrent occurrences inside the caller-owned transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, incident: DiagnosticIncident) -> DiagnosticIncident:
        """Upsert by fingerprint and return the durable aggregate."""
        values = _to_values(incident)
        insert_statement = insert(DiagnosticIncidentRecord).values(**values)
        excluded = insert_statement.excluded
        statement = insert_statement.on_conflict_do_update(
            index_elements=[DiagnosticIncidentRecord.fingerprint],
            set_={
                "last_seen_at": func.greatest(
                    DiagnosticIncidentRecord.last_seen_at, excluded.last_seen_at
                ),
                "last_request_id": excluded.last_request_id,
                "occurrence_count": (
                    DiagnosticIncidentRecord.occurrence_count
                    + excluded.occurrence_count
                ),
                "user_id": func.coalesce(
                    DiagnosticIncidentRecord.user_id, excluded.user_id
                ),
                "tenant_id": func.coalesce(
                    DiagnosticIncidentRecord.tenant_id, excluded.tenant_id
                ),
                "stack_frames": excluded.stack_frames,
            },
        ).returning(DiagnosticIncidentRecord)
        record = (await self._session.execute(statement)).scalar_one()
        return _to_domain(record)

    async def get_by_id(self, incident_id: UUID) -> DiagnosticIncident | None:
        """Return one incident by identifier."""
        record = await self._session.get(DiagnosticIncidentRecord, incident_id)
        return _to_domain(record) if record is not None else None

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
        """Return filtered aggregates and total count in stable order."""
        _validate_page(limit, offset)
        filters = []
        if source is not None:
            filters.append(DiagnosticIncidentRecord.source == source.value)
        if severity is not None:
            filters.append(DiagnosticIncidentRecord.severity == severity.value)
        if component is not None:
            filters.append(DiagnosticIncidentRecord.component == component)
        if environment is not None:
            filters.append(DiagnosticIncidentRecord.environment == environment)
        total = await self._session.scalar(
            select(func.count()).select_from(DiagnosticIncidentRecord).where(*filters)
        )
        records = await self._session.scalars(
            select(DiagnosticIncidentRecord)
            .where(*filters)
            .order_by(
                DiagnosticIncidentRecord.last_seen_at.desc(),
                DiagnosticIncidentRecord.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        return tuple(_to_domain(record) for record in records), int(total or 0)

    async def delete_last_seen_before(self, cutoff: datetime) -> int:
        """Delete expired aggregates according to application retention policy."""
        deleted_ids = await self._session.scalars(
            delete(DiagnosticIncidentRecord)
            .where(DiagnosticIncidentRecord.last_seen_at < cutoff)
            .returning(DiagnosticIncidentRecord.id)
        )
        return len(tuple(deleted_ids))


def _to_values(incident: DiagnosticIncident) -> dict[str, object]:
    return {
        "id": incident.id,
        "fingerprint": incident.fingerprint,
        "source": incident.source.value,
        "severity": incident.severity.value,
        "code": incident.code,
        "component": incident.component,
        "action": incident.action,
        "route": incident.route,
        "method": incident.method,
        "status_code": incident.status_code,
        "tenant_id": incident.tenant_id,
        "user_id": incident.user_id,
        "error_type": incident.error_type,
        "environment": incident.environment,
        "release": incident.release,
        "first_request_id": incident.first_request_id,
        "last_request_id": incident.last_request_id,
        "stack_frames": list(incident.stack_frames),
        "first_seen_at": incident.first_seen_at,
        "last_seen_at": incident.last_seen_at,
        "occurrence_count": incident.occurrence_count,
    }


def _to_domain(record: DiagnosticIncidentRecord) -> DiagnosticIncident:
    return DiagnosticIncident(
        id=record.id,
        fingerprint=record.fingerprint,
        source=DiagnosticSource(record.source),
        severity=DiagnosticSeverity(record.severity),
        code=record.code,
        component=record.component,
        action=record.action,
        route=record.route,
        method=record.method,
        status_code=record.status_code,
        tenant_id=record.tenant_id,
        user_id=record.user_id,
        error_type=record.error_type,
        environment=record.environment,
        release=record.release,
        first_request_id=record.first_request_id,
        last_request_id=record.last_request_id,
        stack_frames=tuple(str(frame) for frame in record.stack_frames),
        first_seen_at=record.first_seen_at,
        last_seen_at=record.last_seen_at,
        occurrence_count=record.occurrence_count,
    )


def _validate_page(limit: int, offset: int) -> None:
    if not 1 <= limit <= 100:
        raise ValueError("Diagnostic page limit must be between 1 and 100.")
    if offset < 0:
        raise ValueError("Diagnostic page offset cannot be negative.")
