"""SQLAlchemy storage model for sanitized operational incidents."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class DiagnosticIncidentRecord(Base):
    """Mutable deduplication aggregate, separate from immutable business audit."""

    __tablename__ = "diagnostic_incidents"
    __table_args__ = (
        CheckConstraint(
            "source IN ('backend', 'frontend')",
            name="ck_diagnostic_incidents_source",
        ),
        CheckConstraint(
            "severity IN ('warning', 'error', 'critical')",
            name="ck_diagnostic_incidents_severity",
        ),
        CheckConstraint(
            "occurrence_count >= 1 AND last_seen_at >= first_seen_at",
            name="ck_diagnostic_incidents_aggregate",
        ),
        CheckConstraint(
            "status_code IS NULL OR status_code BETWEEN 100 AND 599",
            name="ck_diagnostic_incidents_status",
        ),
        CheckConstraint(
            "position('?' in route) = 0",
            name="ck_diagnostic_incidents_route",
        ),
        Index("uq_diagnostic_incidents_fingerprint", "fingerprint", unique=True),
        Index("ix_diagnostic_incidents_last_seen", "last_seen_at", "id"),
        Index(
            "ix_diagnostic_incidents_severity_time",
            "severity",
            "last_seen_at",
        ),
        Index(
            "ix_diagnostic_incidents_component_time",
            "component",
            "last_seen_at",
        ),
        Index(
            "ix_diagnostic_incidents_tenant_time",
            "tenant_id",
            "last_seen_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    component: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    route: Mapped[str] = mapped_column(String(255), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tenant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    error_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    environment: Mapped[str] = mapped_column(String(64), nullable=False)
    release: Mapped[str] = mapped_column(String(128), nullable=False)
    first_request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    last_request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    stack_frames: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)
