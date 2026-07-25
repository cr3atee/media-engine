"""create price_snapshots table

Revision ID: 0004_create_price_snapshots
Revises: 0003_create_canonical_products
Create Date: 2026-07-26 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0004_create_price_snapshots"
down_revision = "0003_create_canonical_products"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "price_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("marketplace", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("collected_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("price_snapshots")
