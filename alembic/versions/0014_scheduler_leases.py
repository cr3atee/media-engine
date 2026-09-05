"""scheduler leases

Revision ID: 0014_scheduler_leases
Revises: 0013_marketplace_credentials
Create Date: 2026-09-03 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0014_scheduler_leases"
down_revision = "0013_marketplace_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scheduler_leases",
        sa.Column("job_name", sa.String(length=255), nullable=False),
        sa.Column("owner_id", sa.String(length=255), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(btrim(job_name)) > 0",
            name="ck_scheduler_leases_job_name_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(owner_id)) > 0",
            name="ck_scheduler_leases_owner_id_nonempty",
        ),
        sa.CheckConstraint(
            "expires_at > acquired_at",
            name="ck_scheduler_leases_expiry_after_acquisition",
        ),
        sa.PrimaryKeyConstraint("job_name", name="pk_scheduler_leases"),
    )
    op.create_index(
        "ix_scheduler_leases_expires_at",
        "scheduler_leases",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_scheduler_leases_expires_at", table_name="scheduler_leases")
    op.drop_table("scheduler_leases")
