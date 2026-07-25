"""create canonical_products table

Revision ID: 0003_create_canonical_products
Revises: 0002_create_offers
Create Date: 2026-07-25 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003_create_canonical_products"
down_revision = "0002_create_offers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canonical_products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=255), nullable=True),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("canonical_products")
