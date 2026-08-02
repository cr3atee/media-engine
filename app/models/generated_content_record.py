from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.domain.tenancy import LEGACY_TENANT_ID


class GeneratedContentRecord(Base):
    """SQLAlchemy persistence model for immutable content attempts."""

    __tablename__ = "generated_contents"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_generated_contents"),
        UniqueConstraint(
            "id",
            "tenant_id",
            name="uq_generated_contents_id_tenant",
        ),
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_generated_contents_idempotency_key",
        ),
        UniqueConstraint(
            "tenant_id",
            "event_id",
            "content_type",
            "language",
            "prompt_version",
            "attempt_number",
            name="uq_generated_contents_event_attempt",
        ),
        ForeignKeyConstraint(
            ("tenant_id",),
            ("tenants.id",),
            name="fk_generated_contents_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("event_id",),
            ("market_events.id",),
            name="fk_generated_contents_event",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("parent_content_id",),
            ("generated_contents.id",),
            name="fk_generated_contents_parent",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("event_id", "tenant_id"),
            ("market_events.id", "market_events.tenant_id"),
            name="fk_generated_contents_event_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("parent_content_id", "tenant_id"),
            ("generated_contents.id", "generated_contents.tenant_id"),
            name="fk_generated_contents_parent_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "generation_status IN "
            "('pending', 'in_progress', 'generated', 'failed', 'abandoned')",
            name="ck_generated_contents_generation_status",
        ),
        CheckConstraint(
            "review_status IN ('not_required', 'pending', 'approved', 'rejected')",
            name="ck_generated_contents_review_status",
        ),
        CheckConstraint(
            "origin IN ('ai', 'human_edit')",
            name="ck_generated_contents_origin",
        ),
        CheckConstraint(
            "attempt_number >= 1",
            name="ck_generated_contents_attempt_number",
        ),
        CheckConstraint("version >= 1", name="ck_generated_contents_version"),
        CheckConstraint(
            "(generation_status = 'in_progress' "
            "AND claim_token IS NOT NULL "
            "AND worker_id IS NOT NULL "
            "AND claimed_at IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR "
            "(generation_status <> 'in_progress' "
            "AND claim_token IS NULL "
            "AND worker_id IS NULL "
            "AND claimed_at IS NULL "
            "AND lease_expires_at IS NULL)",
            name="ck_generated_contents_claim_state",
        ),
        CheckConstraint(
            "lease_expires_at IS NULL OR lease_expires_at > claimed_at",
            name="ck_generated_contents_lease_window",
        ),
        CheckConstraint(
            "(last_error_code IS NULL) = (last_error_summary IS NULL)",
            name="ck_generated_contents_last_error_pair",
        ),
        CheckConstraint(
            "(generation_status = 'generated' "
            "AND content_text IS NOT NULL "
            "AND btrim(content_text) <> '' "
            "AND content_checksum IS NOT NULL "
            "AND completed_at IS NOT NULL) OR "
            "(generation_status <> 'generated' AND content_checksum IS NULL)",
            name="ck_generated_contents_terminal_payload",
        ),
        CheckConstraint(
            "generation_status <> 'failed' OR "
            "(last_error_code IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_generated_contents_failed_payload",
        ),
        CheckConstraint(
            "updated_at >= created_at AND "
            "(completed_at IS NULL OR completed_at >= created_at)",
            name="ck_generated_contents_timestamp_order",
        ),
        Index(
            "uq_generated_contents_active_generation",
            "tenant_id",
            "event_id",
            "content_type",
            "language",
            "prompt_version",
            unique=True,
            postgresql_where=text("generation_status IN ('pending', 'in_progress')"),
        ),
        Index(
            "ix_generated_contents_claim",
            "generation_status",
            "next_retry_at",
            "created_at",
            "id",
            postgresql_where=text("generation_status IN ('pending', 'failed')"),
        ),
        Index(
            "ix_generated_contents_lease_expiry",
            "lease_expires_at",
            "created_at",
            "id",
            postgresql_where=text("generation_status = 'in_progress'"),
        ),
        Index(
            "ix_generated_contents_event_created",
            "tenant_id",
            "event_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_generated_contents_review",
            "review_status",
            "created_at",
            postgresql_where=text("review_status = 'pending'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        nullable=False,
        default=LEGACY_TENANT_ID,
    )
    event_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    parent_content_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    content_checksum: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    claim_token: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error_summary: Mapped[str | None] = mapped_column(
        String(2000),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
