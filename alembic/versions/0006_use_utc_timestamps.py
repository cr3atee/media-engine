"""use timezone-aware UTC timestamps

Revision ID: 0006_use_utc_timestamps
Revises: 0005_add_persistence_integrity
Create Date: 2026-07-29 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0006_use_utc_timestamps"
down_revision = "0005_add_persistence_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "offers",
        "created_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=False,
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "canonical_products",
        "created_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=False,
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "price_snapshots",
        "collected_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=False,
        postgresql_using="collected_at AT TIME ZONE 'UTC'",
    )


def downgrade() -> None:
    op.alter_column(
        "price_snapshots",
        "collected_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        existing_nullable=False,
        postgresql_using="collected_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "canonical_products",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        existing_nullable=False,
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "offers",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        existing_nullable=False,
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
