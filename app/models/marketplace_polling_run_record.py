from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class MarketplacePollingRunRecord(Base):
    """SQLAlchemy record for immutable tenant-scoped polling diagnostics."""

    __tablename__ = "marketplace_polling_runs"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(marketplace)) > 0",
            name="ck_marketplace_polling_runs_marketplace_nonempty",
        ),
        CheckConstraint(
            "status IN ('succeeded', 'failed', 'skipped')",
            name="ck_marketplace_polling_runs_status",
        ),
        CheckConstraint(
            "finished_at >= started_at",
            name="ck_marketplace_polling_runs_time_order",
        ),
        CheckConstraint(
            "offers_received IS NULL OR offers_received >= 0",
            name="ck_marketplace_polling_runs_offers_received",
        ),
        CheckConstraint(
            "offers_persisted IS NULL OR offers_persisted >= 0",
            name="ck_marketplace_polling_runs_offers_persisted",
        ),
        CheckConstraint(
            "snapshots_created IS NULL OR snapshots_created >= 0",
            name="ck_marketplace_polling_runs_snapshots_created",
        ),
        CheckConstraint(
            "snapshots_persisted IS NULL OR snapshots_persisted >= 0",
            name="ck_marketplace_polling_runs_snapshots_persisted",
        ),
        CheckConstraint(
            "price_changes_detected IS NULL OR price_changes_detected >= 0",
            name="ck_marketplace_polling_runs_price_changes",
        ),
        CheckConstraint(
            "events_created IS NULL OR events_created >= 0",
            name="ck_marketplace_polling_runs_events_created",
        ),
        CheckConstraint(
            "processing_error_count IS NULL OR processing_error_count >= 0",
            name="ck_marketplace_polling_runs_processing_errors",
        ),
        CheckConstraint(
            "(status = 'succeeded' AND skipped_reason IS NULL "
            "AND error_code IS NULL AND error_summary IS NULL) OR "
            "(status = 'failed' AND skipped_reason IS NULL "
            "AND error_code IS NOT NULL AND error_summary IS NOT NULL) OR "
            "(status = 'skipped' AND skipped_reason IS NOT NULL "
            "AND error_code IS NULL AND error_summary IS NULL)",
            name="ck_marketplace_polling_runs_outcome",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "integration_id"],
            ["marketplace_integrations.tenant_id", "marketplace_integrations.id"],
            name="fk_marketplace_polling_runs_integration",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_marketplace_polling_runs_integration_finished",
            "tenant_id",
            "integration_id",
            text("finished_at DESC"),
            text("id DESC"),
        ),
        Index(
            "ix_marketplace_polling_runs_status_finished",
            "tenant_id",
            "status",
            text("finished_at DESC"),
            text("id DESC"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    integration_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    marketplace: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    offers_received: Mapped[int | None] = mapped_column(Integer, nullable=True)
    offers_persisted: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snapshots_created: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snapshots_persisted: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_changes_detected: Mapped[int | None] = mapped_column(Integer, nullable=True)
    events_created: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processing_error_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skipped_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(String(2000), nullable=True)
