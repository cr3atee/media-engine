"""marketplace polling run history

Revision ID: 0017_marketplace_polling_runs
Revises: 0016_canonical_offer_decisions
Create Date: 2026-10-06 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0017_marketplace_polling_runs"
down_revision = "0016_canonical_offer_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_marketplace_integrations_tenant_id",
        "marketplace_integrations",
        ["tenant_id", "id"],
    )
    op.create_table(
        "marketplace_polling_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("integration_id", sa.Uuid(), nullable=False),
        sa.Column("marketplace", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("offers_received", sa.Integer(), nullable=True),
        sa.Column("offers_persisted", sa.Integer(), nullable=True),
        sa.Column("snapshots_created", sa.Integer(), nullable=True),
        sa.Column("snapshots_persisted", sa.Integer(), nullable=True),
        sa.Column("price_changes_detected", sa.Integer(), nullable=True),
        sa.Column("events_created", sa.Integer(), nullable=True),
        sa.Column("processing_error_count", sa.Integer(), nullable=True),
        sa.Column("skipped_reason", sa.String(length=128), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_summary", sa.String(length=2000), nullable=True),
        sa.CheckConstraint(
            "length(btrim(marketplace)) > 0",
            name="ck_marketplace_polling_runs_marketplace_nonempty",
        ),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed', 'skipped')",
            name="ck_marketplace_polling_runs_status",
        ),
        sa.CheckConstraint(
            "finished_at >= started_at",
            name="ck_marketplace_polling_runs_time_order",
        ),
        sa.CheckConstraint(
            "offers_received IS NULL OR offers_received >= 0",
            name="ck_marketplace_polling_runs_offers_received",
        ),
        sa.CheckConstraint(
            "offers_persisted IS NULL OR offers_persisted >= 0",
            name="ck_marketplace_polling_runs_offers_persisted",
        ),
        sa.CheckConstraint(
            "snapshots_created IS NULL OR snapshots_created >= 0",
            name="ck_marketplace_polling_runs_snapshots_created",
        ),
        sa.CheckConstraint(
            "snapshots_persisted IS NULL OR snapshots_persisted >= 0",
            name="ck_marketplace_polling_runs_snapshots_persisted",
        ),
        sa.CheckConstraint(
            "price_changes_detected IS NULL OR price_changes_detected >= 0",
            name="ck_marketplace_polling_runs_price_changes",
        ),
        sa.CheckConstraint(
            "events_created IS NULL OR events_created >= 0",
            name="ck_marketplace_polling_runs_events_created",
        ),
        sa.CheckConstraint(
            "processing_error_count IS NULL OR processing_error_count >= 0",
            name="ck_marketplace_polling_runs_processing_errors",
        ),
        sa.CheckConstraint(
            "(status = 'succeeded' AND skipped_reason IS NULL "
            "AND error_code IS NULL AND error_summary IS NULL) OR "
            "(status = 'failed' AND skipped_reason IS NULL "
            "AND error_code IS NOT NULL AND error_summary IS NOT NULL) OR "
            "(status = 'skipped' AND skipped_reason IS NOT NULL "
            "AND error_code IS NULL AND error_summary IS NULL)",
            name="ck_marketplace_polling_runs_outcome",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "integration_id"],
            ["marketplace_integrations.tenant_id", "marketplace_integrations.id"],
            name="fk_marketplace_polling_runs_integration",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_marketplace_polling_runs"),
    )
    op.create_index(
        "ix_marketplace_polling_runs_integration_finished",
        "marketplace_polling_runs",
        [
            "tenant_id",
            "integration_id",
            sa.text("finished_at DESC"),
            sa.text("id DESC"),
        ],
    )
    op.create_index(
        "ix_marketplace_polling_runs_status_finished",
        "marketplace_polling_runs",
        ["tenant_id", "status", sa.text("finished_at DESC"), sa.text("id DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_marketplace_polling_runs_status_finished",
        table_name="marketplace_polling_runs",
    )
    op.drop_index(
        "ix_marketplace_polling_runs_integration_finished",
        table_name="marketplace_polling_runs",
    )
    op.drop_table("marketplace_polling_runs")
    op.drop_constraint(
        "uq_marketplace_integrations_tenant_id",
        "marketplace_integrations",
        type_="unique",
    )
