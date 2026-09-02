"""marketplace integrations

Revision ID: 0012_marketplace_integrations
Revises: 0011_auth_boundary
Create Date: 2026-09-02 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0012_marketplace_integrations"
down_revision = "0011_auth_boundary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "marketplace_integrations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("marketplace", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("external_account_id", sa.String(length=255), nullable=True),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("auth_type", sa.String(length=32), nullable=False),
        sa.Column("last_successful_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failed_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
        sa.Column("last_error_summary", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "length(btrim(marketplace)) > 0",
            name="ck_marketplace_integrations_marketplace_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(display_name)) > 0",
            name="ck_marketplace_integrations_display_name_nonempty",
        ),
        sa.CheckConstraint(
            "external_account_id IS NULL OR length(btrim(external_account_id)) > 0",
            name="ck_marketplace_integrations_external_account_nonempty",
        ),
        sa.CheckConstraint(
            "source_url IS NULL OR length(btrim(source_url)) > 0",
            name="ck_marketplace_integrations_source_url_nonempty",
        ),
        sa.CheckConstraint(
            "last_error_code IS NULL OR length(btrim(last_error_code)) > 0",
            name="ck_marketplace_integrations_last_error_code_nonempty",
        ),
        sa.CheckConstraint(
            "last_error_summary IS NULL OR length(btrim(last_error_summary)) > 0",
            name="ck_marketplace_integrations_last_error_summary_nonempty",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'disabled', 'error')",
            name="ck_marketplace_integrations_status",
        ),
        sa.CheckConstraint(
            "auth_type IN ('none', 'api_key', 'cookie', 'session')",
            name="ck_marketplace_integrations_auth_type",
        ),
        sa.CheckConstraint("version >= 1", name="ck_marketplace_integrations_version"),
        sa.CheckConstraint(
            "updated_at >= created_at",
            name="ck_marketplace_integrations_timestamp_order",
        ),
        sa.CheckConstraint(
            "last_successful_run_at IS NULL OR last_successful_run_at >= created_at",
            name="ck_marketplace_integrations_success_time",
        ),
        sa.CheckConstraint(
            "last_failed_run_at IS NULL OR last_failed_run_at >= created_at",
            name="ck_marketplace_integrations_failure_time",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_marketplace_integrations_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_marketplace_integrations"),
    )
    op.create_index(
        "uq_marketplace_integrations_tenant_marketplace_external_account",
        "marketplace_integrations",
        ["tenant_id", "marketplace", "external_account_id"],
        unique=True,
        postgresql_where=sa.text("external_account_id IS NOT NULL"),
    )
    op.create_index(
        "uq_marketplace_integrations_tenant_marketplace_source_url",
        "marketplace_integrations",
        ["tenant_id", "marketplace", "source_url"],
        unique=True,
        postgresql_where=sa.text("source_url IS NOT NULL"),
    )
    op.create_index(
        "ix_marketplace_integrations_tenant",
        "marketplace_integrations",
        ["tenant_id", "marketplace", "id"],
    )
    op.create_index(
        "ix_marketplace_integrations_enabled_runs",
        "marketplace_integrations",
        ["enabled", "status", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_marketplace_integrations_enabled_runs",
        table_name="marketplace_integrations",
    )
    op.drop_index(
        "ix_marketplace_integrations_tenant",
        table_name="marketplace_integrations",
    )
    op.drop_index(
        "uq_marketplace_integrations_tenant_marketplace_source_url",
        table_name="marketplace_integrations",
    )
    op.drop_index(
        "uq_marketplace_integrations_tenant_marketplace_external_account",
        table_name="marketplace_integrations",
    )
    op.drop_table("marketplace_integrations")
