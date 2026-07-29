"""create durable market events

Revision ID: 0007_create_market_events
Revises: 0006_use_utc_timestamps
Create Date: 2026-07-29 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0007_create_market_events"
down_revision = "0006_use_utc_timestamps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("identity_key", sa.CHAR(length=64), nullable=False),
        sa.Column("identity_version", sa.SmallInteger(), nullable=False),
        sa.Column("identity_source", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("marketplace", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("canonical_product_id", sa.Uuid(), nullable=True),
        sa.Column("previous_snapshot_id", sa.BigInteger(), nullable=True),
        sa.Column("current_snapshot_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(length=1000), nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=True),
        sa.Column("old_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("new_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column(
            "percentage",
            sa.Numeric(precision=12, scale=6),
            nullable=False,
        ),
        sa.Column("score", sa.SmallInteger(), nullable=True),
        sa.Column("disposition", sa.String(length=32), nullable=False),
        sa.Column("scoring_status", sa.String(length=32), nullable=False),
        sa.Column("scoring_attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("worker_id", sa.String(length=255), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
        sa.Column("last_error_summary", sa.String(length=2000), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "audit_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.CheckConstraint(
            "scoring_attempt_count >= 0",
            name="ck_market_events_attempt_count",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            "disposition IN "
            "('active', 'review_pending', 'approved', 'ignored', 'rejected')",
            name="ck_market_events_disposition",
        ),
        sa.CheckConstraint(
            "event_type IN ('price_drop')",
            name="ck_market_events_event_type",
        ),
        sa.CheckConstraint(
            "identity_source IN ('snapshot_ids', 'legacy_facts')",
            name="ck_market_events_identity_source",
        ),
        sa.CheckConstraint(
            "identity_version >= 1",
            name="ck_market_events_identity_version",
        ),
        sa.CheckConstraint(
            "lease_expires_at IS NULL OR lease_expires_at > claimed_at",
            name="ck_market_events_lease_window",
        ),
        sa.CheckConstraint(
            "(last_error_code IS NULL) = (last_error_summary IS NULL)",
            name="ck_market_events_last_error_pair",
        ),
        sa.CheckConstraint(
            "percentage >= 0",
            name="ck_market_events_percentage_nonnegative",
        ),
        sa.CheckConstraint(
            "event_type <> 'price_drop' OR new_price < old_price",
            name="ck_market_events_price_drop_direction",
        ),
        sa.CheckConstraint(
            "old_price >= 0 AND new_price >= 0",
            name="ck_market_events_prices_nonnegative",
        ),
        sa.CheckConstraint(
            "(scoring_status = 'succeeded' AND score IS NOT NULL) OR "
            "(scoring_status <> 'succeeded' AND score IS NULL)",
            name="ck_market_events_scoring_result",
        ),
        sa.CheckConstraint(
            "scoring_status IN "
            "('pending', 'in_progress', 'succeeded', 'failed', 'skipped')",
            name="ck_market_events_scoring_status",
        ),
        sa.CheckConstraint(
            "score IS NULL OR score BETWEEN 0 AND 100",
            name="ck_market_events_score_range",
        ),
        sa.CheckConstraint(
            "(previous_snapshot_id IS NULL) = (current_snapshot_id IS NULL)",
            name="ck_market_events_snapshot_pair",
        ),
        sa.CheckConstraint(
            "detected_at >= occurred_at "
            "AND created_at >= detected_at "
            "AND updated_at >= created_at",
            name="ck_market_events_timestamp_order",
        ),
        sa.CheckConstraint("version >= 1", name="ck_market_events_version"),
        sa.ForeignKeyConstraint(
            ["canonical_product_id"],
            ["canonical_products.id"],
            name="fk_market_events_canonical_product",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["current_snapshot_id"],
            ["price_snapshots.id"],
            name="fk_market_events_current_snapshot",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["previous_snapshot_id"],
            ["price_snapshots.id"],
            name="fk_market_events_previous_snapshot",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_market_events"),
        sa.UniqueConstraint(
            "identity_key",
            name="uq_market_events_identity_key",
        ),
    )
    op.create_index(
        "ix_market_events_canonical_timeline",
        "market_events",
        ["canonical_product_id", sa.text("occurred_at DESC")],
        unique=False,
        postgresql_where=sa.text("canonical_product_id IS NOT NULL"),
    )
    op.create_index(
        "ix_market_events_lease_expiry",
        "market_events",
        ["lease_expires_at", "created_at", "id"],
        unique=False,
        postgresql_where=sa.text("scoring_status = 'in_progress'"),
    )
    op.create_index(
        "ix_market_events_offer_timeline",
        "market_events",
        ["marketplace", "external_id", sa.text("occurred_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_market_events_scoring_claim",
        "market_events",
        ["scoring_status", "next_retry_at", "created_at", "id"],
        unique=False,
        postgresql_where=sa.text(
            "disposition IN ('active', 'approved') "
            "AND scoring_status IN ('pending', 'failed')"
        ),
    )
    op.create_index(
        "uq_market_events_snapshot_transition",
        "market_events",
        ["event_type", "previous_snapshot_id", "current_snapshot_id"],
        unique=True,
        postgresql_where=sa.text(
            "previous_snapshot_id IS NOT NULL AND current_snapshot_id IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_market_events_snapshot_transition",
        table_name="market_events",
        postgresql_where=sa.text(
            "previous_snapshot_id IS NOT NULL AND current_snapshot_id IS NOT NULL"
        ),
    )
    op.drop_index("ix_market_events_scoring_claim", table_name="market_events")
    op.drop_index("ix_market_events_offer_timeline", table_name="market_events")
    op.drop_index("ix_market_events_lease_expiry", table_name="market_events")
    op.drop_index("ix_market_events_canonical_timeline", table_name="market_events")
    op.drop_table("market_events")
