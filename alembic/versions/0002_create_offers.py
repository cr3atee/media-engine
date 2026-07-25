"""create offers table

Revision ID: 0002_create_offers
Revises: 0001_init_marketplace_support
Create Date: 2026-07-25 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0002_create_offers"
down_revision = "0001_init_marketplace_support"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "offers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("marketplace", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=1000), nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=True),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=16), nullable=True),
        sa.Column("seller_id", sa.String(length=255), nullable=True),
        sa.Column("seller_name", sa.String(length=255), nullable=True),
        sa.Column("canonical_product_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("offers")
