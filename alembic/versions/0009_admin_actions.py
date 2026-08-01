"""create immutable admin actions

Revision ID: 0009_admin_actions
Revises: 0008_content_publications
Create Date: 2026-08-01 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0009_admin_actions"
down_revision = "0008_content_publications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("previous_state", sa.String(length=64), nullable=False),
        sa.Column("resulting_state", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.CHAR(length=64), nullable=False),
        sa.Column("expected_version", sa.Integer(), nullable=False),
        sa.Column("resulting_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint(
            "action IN ("
            "'approve_content', 'reject_content', 'retry_publication', "
            "'cancel_publication', 'resolve_publication_delivered', "
            "'resolve_publication_not_delivered', "
            "'resolve_publication_cancelled')",
            name="ck_admin_actions_action",
        ),
        sa.CheckConstraint(
            "resource_type IN ('content', 'publication')",
            name="ck_admin_actions_resource_type",
        ),
        sa.CheckConstraint(
            "expected_version >= 1 AND resulting_version > expected_version",
            name="ck_admin_actions_versions",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_actions"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_admin_actions_idempotency_key",
        ),
    )
    op.create_index(
        "ix_admin_actions_actor_created",
        "admin_actions",
        ["actor_id", sa.text("created_at DESC"), sa.text("id DESC")],
        unique=False,
    )
    op.create_index(
        "ix_admin_actions_created",
        "admin_actions",
        [sa.text("created_at DESC"), sa.text("id DESC")],
        unique=False,
    )
    op.create_index(
        "ix_admin_actions_request_id",
        "admin_actions",
        ["request_id", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_admin_actions_resource_created",
        "admin_actions",
        [
            "resource_type",
            "resource_id",
            sa.text("created_at DESC"),
            sa.text("id DESC"),
        ],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_admin_actions_resource_created", table_name="admin_actions")
    op.drop_index("ix_admin_actions_request_id", table_name="admin_actions")
    op.drop_index("ix_admin_actions_created", table_name="admin_actions")
    op.drop_index("ix_admin_actions_actor_created", table_name="admin_actions")
    op.drop_table("admin_actions")
