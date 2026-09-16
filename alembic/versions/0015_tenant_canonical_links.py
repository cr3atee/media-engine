"""tenant-safe canonical offer links

Revision ID: 0015_tenant_canonical_links
Revises: 0014_scheduler_leases
Create Date: 2026-09-16 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0015_tenant_canonical_links"
down_revision = "0014_scheduler_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM offers AS offer
                    JOIN canonical_products AS product
                        ON product.id = offer.canonical_product_id
                    WHERE offer.canonical_product_id IS NOT NULL
                        AND offer.tenant_id <> product.tenant_id
                ) THEN
                    RAISE EXCEPTION
                        'Cross-tenant canonical offer links block migration 0015'
                        USING HINT = 'Review and repair invalid links explicitly';
                END IF;
            END
            $$;
            """
        )
    )
    op.create_unique_constraint(
        "uq_canonical_products_tenant_id_id",
        "canonical_products",
        ["tenant_id", "id"],
    )
    op.create_foreign_key(
        "fk_offers_tenant_canonical_product",
        "offers",
        "canonical_products",
        ["tenant_id", "canonical_product_id"],
        ["tenant_id", "id"],
    )
    op.create_index(
        "ix_offers_tenant_canonical_product",
        "offers",
        ["tenant_id", "canonical_product_id"],
        unique=False,
        postgresql_where=sa.text("canonical_product_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_offers_tenant_canonical_product",
        table_name="offers",
        postgresql_where=sa.text("canonical_product_id IS NOT NULL"),
    )
    op.drop_constraint(
        "fk_offers_tenant_canonical_product",
        "offers",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_canonical_products_tenant_id_id",
        "canonical_products",
        type_="unique",
    )
