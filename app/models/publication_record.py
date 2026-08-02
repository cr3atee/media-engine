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
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.domain.tenancy import LEGACY_TENANT_ID


class PublicationRecord(Base):
    """SQLAlchemy persistence model for channel-neutral publication intent."""

    __tablename__ = "publications"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_publications"),
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_publications_idempotency_key",
        ),
        UniqueConstraint(
            "tenant_id",
            "content_id",
            "channel",
            "destination_key",
            name="uq_publications_content_channel_destination",
        ),
        ForeignKeyConstraint(
            ("tenant_id",),
            ("tenants.id",),
            name="fk_publications_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("event_id",),
            ("market_events.id",),
            name="fk_publications_event",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("content_id",),
            ("generated_contents.id",),
            name="fk_publications_content",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "publication_status IN "
            "('pending', 'in_progress', 'published', 'failed', "
            "'ambiguous', 'cancelled')",
            name="ck_publications_status",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_publications_attempt_count",
        ),
        CheckConstraint("version >= 1", name="ck_publications_version"),
        CheckConstraint(
            "(publication_status = 'in_progress' "
            "AND claim_token IS NOT NULL "
            "AND worker_id IS NOT NULL "
            "AND claimed_at IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR "
            "(publication_status <> 'in_progress' "
            "AND claim_token IS NULL "
            "AND worker_id IS NULL "
            "AND claimed_at IS NULL "
            "AND lease_expires_at IS NULL)",
            name="ck_publications_claim_state",
        ),
        CheckConstraint(
            "lease_expires_at IS NULL OR lease_expires_at > claimed_at",
            name="ck_publications_lease_window",
        ),
        CheckConstraint(
            "(last_error_code IS NULL) = (last_error_summary IS NULL)",
            name="ck_publications_last_error_pair",
        ),
        CheckConstraint(
            "publication_status NOT IN ('failed', 'ambiguous') OR "
            "last_error_code IS NOT NULL",
            name="ck_publications_failure_payload",
        ),
        CheckConstraint(
            "(publication_status = 'published' "
            "AND published_at IS NOT NULL "
            "AND external_message_id IS NOT NULL "
            "AND btrim(external_message_id) <> '') OR "
            "(publication_status <> 'published' "
            "AND published_at IS NULL "
            "AND external_message_id IS NULL)",
            name="ck_publications_published_payload",
        ),
        CheckConstraint(
            "updated_at >= created_at AND "
            "(published_at IS NULL OR published_at >= created_at)",
            name="ck_publications_timestamp_order",
        ),
        Index(
            "ix_publications_claim",
            "publication_status",
            "scheduled_at",
            "next_retry_at",
            "created_at",
            "id",
            postgresql_where=text("publication_status IN ('pending', 'failed')"),
        ),
        Index(
            "ix_publications_lease_expiry",
            "lease_expires_at",
            "created_at",
            "id",
            postgresql_where=text("publication_status = 'in_progress'"),
        ),
        Index(
            "ix_publications_event_created",
            "tenant_id",
            "event_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_publications_status_schedule",
            "tenant_id",
            "publication_status",
            "scheduled_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        nullable=False,
        default=LEGACY_TENANT_ID,
    )
    event_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    content_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    destination_key: Mapped[str] = mapped_column(String(255), nullable=False)
    publication_status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    external_message_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(
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
    version: Mapped[int] = mapped_column(Integer, nullable=False)
