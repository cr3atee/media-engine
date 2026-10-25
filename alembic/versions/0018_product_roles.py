"""Explicit product roles and immutable platform role audit.

Revision ID: 0018_product_roles
Revises: 0017_marketplace_polling_runs
"""

import sqlalchemy as sa

from alembic import op

revision = "0018_product_roles"
down_revision = "0017_marketplace_polling_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Backfill only the unprivileged role; workspace ownership never grants admin."""
    op.add_column(
        "users",
        sa.Column("product_role", sa.String(16), nullable=False, server_default="user"),
    )
    op.create_check_constraint(
        "ck_users_product_role",
        "users",
        "product_role IN ('user', 'partner', 'moderator', 'admin')",
    )
    op.create_index(
        "ix_users_product_role_enabled", "users", ["product_role", "enabled"]
    )
    op.create_table(
        "product_role_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("actor_key", sa.String(36), nullable=False),
        sa.Column("previous_role", sa.String(16), nullable=False),
        sa.Column("resulting_role", sa.String(16), nullable=False),
        sa.Column("expected_version", sa.Integer(), nullable=False),
        sa.Column("resulting_version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "previous_role IN ('user', 'partner', 'moderator', 'admin') "
            "AND resulting_role IN ('user', 'partner', 'moderator', 'admin')",
            name="ck_product_role_actions_roles",
        ),
        sa.CheckConstraint(
            "expected_version >= 1 AND resulting_version = expected_version + 1",
            name="ck_product_role_actions_versions",
        ),
        sa.CheckConstraint(
            "length(btrim(reason)) > 0 AND length(btrim(idempotency_key)) > 0",
            name="ck_product_role_actions_nonempty",
        ),
        sa.CheckConstraint(
            "(actor_user_id IS NULL AND actor_key = 'bootstrap') "
            "OR (actor_user_id IS NOT NULL "
            "AND actor_key = CAST(actor_user_id AS VARCHAR))",
            name="ck_product_role_actions_actor",
        ),
    )
    op.create_index(
        "uq_product_role_actions_replay",
        "product_role_actions",
        ["actor_key", "idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_product_role_actions_user_time",
        "product_role_actions",
        ["user_id", "created_at", "id"],
    )
    op.execute("""CREATE FUNCTION reject_product_role_audit_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        RAISE EXCEPTION 'Product role audit is immutable'; END; $$""")
    op.execute("""CREATE TRIGGER product_role_audit_immutable
        BEFORE UPDATE OR DELETE OR TRUNCATE ON product_role_actions
        FOR EACH STATEMENT EXECUTE FUNCTION reject_product_role_audit_mutation()""")


def downgrade() -> None:
    """Drop role grants and audit; operators must explicitly accept this data loss."""
    op.drop_table("product_role_actions")
    op.execute("DROP FUNCTION reject_product_role_audit_mutation()")
    op.drop_index("ix_users_product_role_enabled", table_name="users")
    op.drop_constraint("ck_users_product_role", "users", type_="check")
    op.drop_column("users", "product_role")
