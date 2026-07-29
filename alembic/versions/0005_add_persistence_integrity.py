"""add persistence integrity

Revision ID: 0005_add_persistence_integrity
Revises: 0004_create_price_snapshots
Create Date: 2026-07-29 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0005_add_persistence_integrity"
down_revision = "0004_create_price_snapshots"
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
                    FROM offers
                    WHERE external_id IS NOT NULL
                    GROUP BY marketplace, external_id
                    HAVING COUNT(*) > 1
                ) THEN
                    RAISE EXCEPTION
                        'Duplicate offer identities block Task 5 migration'
                        USING HINT = 'Manually resolve duplicate offers';
                END IF;

                IF EXISTS (
                    SELECT 1
                    FROM price_snapshots
                    GROUP BY marketplace, external_id, collected_at, price, currency
                    HAVING COUNT(*) > 1
                ) THEN
                    RAISE EXCEPTION
                        'Exact duplicate snapshots block Task 5 migration'
                        USING HINT = 'Manually resolve duplicate snapshots';
                END IF;

                IF EXISTS (
                    SELECT 1
                    FROM offers AS offer
                    LEFT JOIN canonical_products AS product
                        ON product.id = offer.canonical_product_id
                    WHERE offer.canonical_product_id IS NOT NULL
                        AND product.id IS NULL
                ) THEN
                    RAISE EXCEPTION
                        'Orphan canonical references block Task 5 migration'
                        USING HINT = 'Manually resolve orphan references';
                END IF;
            END
            $$;
            """,
        ),
    )

    op.create_index(
        "uq_offers_marketplace_external_id_not_null",
        "offers",
        ["marketplace", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )
    op.create_index(
        "ix_offers_canonical_product_id",
        "offers",
        ["canonical_product_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_offers_canonical_product_id_canonical_products",
        "offers",
        "canonical_products",
        ["canonical_product_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_price_snapshots_exact_identity",
        "price_snapshots",
        ["marketplace", "external_id", "collected_at", "price", "currency"],
    )
    op.create_index(
        "ix_price_snapshots_history_order",
        "price_snapshots",
        ["marketplace", "external_id", "collected_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_price_snapshots_history_order",
        table_name="price_snapshots",
    )
    op.drop_constraint(
        "uq_price_snapshots_exact_identity",
        "price_snapshots",
        type_="unique",
    )
    op.drop_constraint(
        "fk_offers_canonical_product_id_canonical_products",
        "offers",
        type_="foreignkey",
    )
    op.drop_index("ix_offers_canonical_product_id", table_name="offers")
    op.drop_index(
        "uq_offers_marketplace_external_id_not_null",
        table_name="offers",
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )
