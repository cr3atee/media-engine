from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.domain.tenancy import LEGACY_TENANT_ID


class MarketEventRecord(Base):
    """SQLAlchemy persistence model for durable market events."""

    __tablename__ = "market_events"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_market_events"),
        UniqueConstraint(
            "id",
            "tenant_id",
            name="uq_market_events_id_tenant",
        ),
        UniqueConstraint(
            "tenant_id",
            "identity_key",
            name="uq_market_events_identity_key",
        ),
        ForeignKeyConstraint(
            ("tenant_id",),
            ("tenants.id",),
            name="fk_market_events_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("canonical_product_id",),
            ("canonical_products.id",),
            name="fk_market_events_canonical_product",
            ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            ("previous_snapshot_id",),
            ("price_snapshots.id",),
            name="fk_market_events_previous_snapshot",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("current_snapshot_id",),
            ("price_snapshots.id",),
            name="fk_market_events_current_snapshot",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("previous_snapshot_id", "tenant_id"),
            ("price_snapshots.id", "price_snapshots.tenant_id"),
            name="fk_market_events_previous_snapshot_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("current_snapshot_id", "tenant_id"),
            ("price_snapshots.id", "price_snapshots.tenant_id"),
            name="fk_market_events_current_snapshot_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(previous_snapshot_id IS NULL) = (current_snapshot_id IS NULL)",
            name="ck_market_events_snapshot_pair",
        ),
        CheckConstraint(
            "old_price >= 0 AND new_price >= 0",
            name="ck_market_events_prices_nonnegative",
        ),
        CheckConstraint(
            "event_type <> 'price_drop' OR new_price < old_price",
            name="ck_market_events_price_drop_direction",
        ),
        CheckConstraint(
            "percentage >= 0",
            name="ck_market_events_percentage_nonnegative",
        ),
        CheckConstraint(
            "score IS NULL OR score BETWEEN 0 AND 100",
            name="ck_market_events_score_range",
        ),
        CheckConstraint(
            "disposition IN "
            "('active', 'review_pending', 'approved', 'ignored', 'rejected')",
            name="ck_market_events_disposition",
        ),
        CheckConstraint(
            "scoring_status IN "
            "('pending', 'in_progress', 'succeeded', 'failed', 'skipped')",
            name="ck_market_events_scoring_status",
        ),
        CheckConstraint(
            "event_type IN ('price_drop')",
            name="ck_market_events_event_type",
        ),
        CheckConstraint(
            "identity_source IN ('snapshot_ids', 'legacy_facts')",
            name="ck_market_events_identity_source",
        ),
        CheckConstraint(
            "scoring_attempt_count >= 0",
            name="ck_market_events_attempt_count",
        ),
        CheckConstraint(
            "identity_version >= 1",
            name="ck_market_events_identity_version",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_market_events_version",
        ),
        CheckConstraint(
            "(scoring_status = 'succeeded' AND score IS NOT NULL) OR "
            "(scoring_status <> 'succeeded' AND score IS NULL)",
            name="ck_market_events_scoring_result",
        ),
        CheckConstraint(
            "(scoring_status = 'in_progress' "
            "AND claim_token IS NOT NULL "
            "AND worker_id IS NOT NULL "
            "AND claimed_at IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR "
            "(scoring_status <> 'in_progress' "
            "AND claim_token IS NULL "
            "AND worker_id IS NULL "
            "AND claimed_at IS NULL "
            "AND lease_expires_at IS NULL)",
            name="ck_market_events_claim_state",
        ),
        CheckConstraint(
            "lease_expires_at IS NULL OR lease_expires_at > claimed_at",
            name="ck_market_events_lease_window",
        ),
        CheckConstraint(
            "(last_error_code IS NULL) = (last_error_summary IS NULL)",
            name="ck_market_events_last_error_pair",
        ),
        CheckConstraint(
            "detected_at >= occurred_at "
            "AND created_at >= detected_at "
            "AND updated_at >= created_at",
            name="ck_market_events_timestamp_order",
        ),
        Index(
            "uq_market_events_snapshot_transition",
            "tenant_id",
            "event_type",
            "previous_snapshot_id",
            "current_snapshot_id",
            unique=True,
            postgresql_where=text(
                "previous_snapshot_id IS NOT NULL AND current_snapshot_id IS NOT NULL"
            ),
        ),
        Index(
            "ix_market_events_scoring_claim",
            "scoring_status",
            "next_retry_at",
            "created_at",
            "id",
            postgresql_where=text(
                "disposition IN ('active', 'approved') "
                "AND scoring_status IN ('pending', 'failed')"
            ),
        ),
        Index(
            "ix_market_events_lease_expiry",
            "lease_expires_at",
            "created_at",
            "id",
            postgresql_where=text("scoring_status = 'in_progress'"),
        ),
        Index(
            "ix_market_events_offer_timeline",
            "tenant_id",
            "marketplace",
            "external_id",
            text("occurred_at DESC"),
        ),
        Index(
            "ix_market_events_canonical_timeline",
            "tenant_id",
            "canonical_product_id",
            text("occurred_at DESC"),
            postgresql_where=text("canonical_product_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        nullable=False,
        default=LEGACY_TENANT_ID,
    )
    identity_key: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    identity_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    identity_source: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    marketplace: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_product_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        nullable=True,
    )
    previous_snapshot_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    current_snapshot_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    title: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    old_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    new_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    percentage: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    disposition: Mapped[str] = mapped_column(String(32), nullable=False)
    scoring_status: Mapped[str] = mapped_column(String(32), nullable=False)
    scoring_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
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
    last_error_code: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    last_error_summary: Mapped[str | None] = mapped_column(
        String(2000),
        nullable=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
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
    audit_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
