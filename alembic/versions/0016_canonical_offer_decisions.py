"""canonical offer review decisions

Revision ID: 0016_canonical_offer_decisions
Revises: 0015_tenant_canonical_links
Create Date: 2026-09-16 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0016_canonical_offer_decisions"
down_revision = "0015_tenant_canonical_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canonical_offer_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("marketplace", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("canonical_product_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.CHAR(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('confirmed', 'rejected')",
            name="ck_canonical_offer_decisions_decision",
        ),
        sa.CheckConstraint(
            "actor_type IN "
            "('api_key', 'platform_admin', 'user', 'system', 'worker', 'migration')",
            name="ck_canonical_offer_decisions_actor_type",
        ),
        sa.CheckConstraint(
            "length(btrim(marketplace)) > 0 "
            "AND length(btrim(external_id)) > 0 "
            "AND length(btrim(actor_id)) > 0 "
            "AND length(btrim(request_id)) > 0 "
            "AND length(btrim(idempotency_key)) > 0",
            name="ck_canonical_offer_decisions_nonempty",
        ),
        sa.CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_canonical_offer_decisions_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_canonical_offer_decisions_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "canonical_product_id"],
            ["canonical_products.tenant_id", "canonical_products.id"],
            name="fk_canonical_offer_decisions_product",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_canonical_offer_decisions"),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_canonical_offer_decisions_idempotency",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "marketplace",
            "external_id",
            "canonical_product_id",
            name="uq_canonical_offer_decisions_pair",
        ),
    )
    op.create_index(
        "ix_canonical_offer_decisions_offer_created",
        "canonical_offer_decisions",
        [
            "tenant_id",
            "marketplace",
            "external_id",
            sa.text("created_at DESC"),
            sa.text("id DESC"),
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_canonical_offer_decisions_offer_created",
        table_name="canonical_offer_decisions",
    )
    op.drop_table("canonical_offer_decisions")
