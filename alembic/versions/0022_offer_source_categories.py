"""Preserve marketplace source categories on parsed offers.

Revision ID: 0022_offer_source_categories
Revises: 0021_offer_manual_availability
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0022_offer_source_categories"
down_revision = "0021_offer_manual_availability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add nullable source category evidence and its tenant lookup index."""
    op.add_column(
        "offers",
        sa.Column("source_category_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "offers",
        sa.Column("source_category_name", sa.String(length=500), nullable=True),
    )
    op.create_index(
        "ix_offers_tenant_marketplace_source_category",
        "offers",
        ["tenant_id", "marketplace", "source_category_id"],
        unique=False,
        postgresql_where=sa.text("source_category_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Remove source category evidence from persisted offers."""
    op.drop_index(
        "ix_offers_tenant_marketplace_source_category",
        table_name="offers",
    )
    op.drop_column("offers", "source_category_name")
    op.drop_column("offers", "source_category_id")
