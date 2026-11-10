"""Persist verified catalog classification on marketplace offers.

Revision ID: 0024_offer_catalog_fields
Revises: 0023_catalog_source_rules
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0024_offer_catalog_fields"
down_revision = "0023_catalog_source_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add tenant-safe source-rule classification fields to offers."""
    op.create_unique_constraint(
        "uq_catalog_source_rules_tenant_id_id",
        "catalog_source_rules",
        ["tenant_id", "id"],
    )
    op.add_column(
        "offers",
        sa.Column("catalog_hub_code", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "offers",
        sa.Column("catalog_section_code", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "offers",
        sa.Column("catalog_source_rule_id", sa.Uuid(), nullable=True),
    )
    op.create_check_constraint(
        "ck_offers_catalog_classification_complete",
        "offers",
        "(catalog_hub_code IS NULL "
        "AND catalog_section_code IS NULL "
        "AND catalog_source_rule_id IS NULL) OR "
        "(catalog_hub_code IS NOT NULL "
        "AND catalog_section_code IS NOT NULL "
        "AND catalog_source_rule_id IS NOT NULL)",
    )
    op.create_foreign_key(
        "fk_offers_tenant_catalog_source_rule",
        "offers",
        "catalog_source_rules",
        ["tenant_id", "catalog_source_rule_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_offers_tenant_catalog_classification",
        "offers",
        ["tenant_id", "catalog_hub_code", "catalog_section_code"],
        unique=False,
        postgresql_where=sa.text("catalog_hub_code IS NOT NULL"),
    )


def downgrade() -> None:
    """Remove persisted offer classification fields and rule identity."""
    op.drop_index(
        "ix_offers_tenant_catalog_classification",
        table_name="offers",
    )
    op.drop_constraint(
        "fk_offers_tenant_catalog_source_rule",
        "offers",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_offers_catalog_classification_complete",
        "offers",
        type_="check",
    )
    op.drop_column("offers", "catalog_source_rule_id")
    op.drop_column("offers", "catalog_section_code")
    op.drop_column("offers", "catalog_hub_code")
    op.drop_constraint(
        "uq_catalog_source_rules_tenant_id_id",
        "catalog_source_rules",
        type_="unique",
    )
