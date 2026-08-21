"""auth boundary

Revision ID: 0011_auth_boundary
Revises: 0010_tenant_identity_foundation
Create Date: 2026-08-21 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0011_auth_boundary"
down_revision = "0010_tenant_identity_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_credentials",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "length(btrim(password_hash)) > 0",
            name="ck_user_credentials_password_hash_nonempty",
        ),
        sa.CheckConstraint("version >= 1", name="ck_user_credentials_version"),
        sa.CheckConstraint(
            "updated_at >= created_at",
            name="ck_user_credentials_timestamp_order",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_credentials_user",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_user_credentials"),
    )

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("refresh_token_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("expires_at > created_at", name="ck_auth_sessions_expiry"),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_auth_sessions_revoked_at",
        ),
        sa.CheckConstraint(
            "last_used_at IS NULL OR last_used_at >= created_at",
            name="ck_auth_sessions_last_used_at",
        ),
        sa.CheckConstraint("version >= 1", name="ck_auth_sessions_version"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_auth_sessions_user",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_auth_sessions"),
    )
    op.create_index(
        "uq_auth_sessions_refresh_token_hash",
        "auth_sessions",
        ["refresh_token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_auth_sessions_user_active",
        "auth_sessions",
        ["user_id", "revoked_at", "expires_at"],
        unique=False,
    )

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_password_reset_tokens_expiry",
        ),
        sa.CheckConstraint(
            "used_at IS NULL OR used_at >= created_at",
            name="ck_password_reset_tokens_used_at",
        ),
        sa.CheckConstraint("version >= 1", name="ck_password_reset_tokens_version"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_password_reset_tokens_user",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_password_reset_tokens"),
    )
    op.create_index(
        "uq_password_reset_tokens_hash",
        "password_reset_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_password_reset_tokens_user",
        "password_reset_tokens",
        ["user_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_password_reset_tokens_user", table_name="password_reset_tokens")
    op.drop_index("uq_password_reset_tokens_hash", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")

    op.drop_index("ix_auth_sessions_user_active", table_name="auth_sessions")
    op.drop_index("uq_auth_sessions_refresh_token_hash", table_name="auth_sessions")
    op.drop_table("auth_sessions")

    op.drop_table("user_credentials")
