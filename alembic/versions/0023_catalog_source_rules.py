"""Add tenant-scoped catalog source classification rules.

Revision ID: 0023_catalog_source_rules
Revises: 0022_offer_source_categories
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0023_catalog_source_rules"
down_revision = "0022_offer_source_categories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create durable mappings from integration categories to catalog sections."""
    op.create_table(
        "catalog_source_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("integration_id", sa.Uuid(), nullable=False),
        sa.Column("marketplace", sa.String(length=64), nullable=False),
        sa.Column("source_category_id", sa.String(length=255), nullable=False),
        sa.Column("source_category_name", sa.String(length=500), nullable=True),
        sa.Column("hub_code", sa.String(length=64), nullable=False),
        sa.Column("section_code", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "length(btrim(marketplace)) > 0",
            name="ck_catalog_source_rules_marketplace_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(source_category_id)) > 0",
            name="ck_catalog_source_rules_source_id_nonempty",
        ),
        sa.CheckConstraint(
            "source_category_name IS NULL OR length(btrim(source_category_name)) > 0",
            name="ck_catalog_source_rules_source_name_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(hub_code)) > 0",
            name="ck_catalog_source_rules_hub_code_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(section_code)) > 0",
            name="ck_catalog_source_rules_section_code_nonempty",
        ),
        sa.CheckConstraint(
            "updated_at >= created_at",
            name="ck_catalog_source_rules_timestamp_order",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_catalog_source_rules_version",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "integration_id"],
            ["marketplace_integrations.tenant_id", "marketplace_integrations.id"],
            name="fk_catalog_source_rules_integration",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "integration_id",
            "marketplace",
            "source_category_id",
            name="uq_catalog_source_rules_source_identity",
        ),
    )
    op.create_index(
        "ix_catalog_source_rules_tenant_hub_section",
        "catalog_source_rules",
        ["tenant_id", "hub_code", "section_code"],
        unique=False,
    )
    op.create_index(
        "ix_catalog_source_rules_tenant_integration",
        "catalog_source_rules",
        ["tenant_id", "integration_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove catalog source classification rules."""
    op.drop_index(
        "ix_catalog_source_rules_tenant_integration",
        table_name="catalog_source_rules",
    )
    op.drop_index(
        "ix_catalog_source_rules_tenant_hub_section",
        table_name="catalog_source_rules",
    )
    op.drop_table("catalog_source_rules")
