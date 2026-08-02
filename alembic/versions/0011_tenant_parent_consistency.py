"""enforce tenant parent consistency

Revision ID: 0011_tenant_parent_consistency
Revises: 0010_tenant_foundation
Create Date: 2026-08-02 00:00:01.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0011_tenant_parent_consistency"
down_revision = "0010_tenant_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _create_parent_identities()
    _create_composite_foreign_keys()
    _create_optional_parent_triggers()


def downgrade() -> None:
    _drop_optional_parent_triggers()
    _drop_composite_foreign_keys()
    _drop_parent_identities()


def _create_parent_identities() -> None:
    op.create_unique_constraint(
        "uq_products_id_tenant",
        "products",
        ["id", "tenant_id"],
    )
    op.create_unique_constraint(
        "uq_canonical_products_id_tenant",
        "canonical_products",
        ["id", "tenant_id"],
    )
    op.create_unique_constraint(
        "uq_price_snapshots_id_tenant",
        "price_snapshots",
        ["id", "tenant_id"],
    )
    op.create_unique_constraint(
        "uq_market_events_id_tenant",
        "market_events",
        ["id", "tenant_id"],
    )
    op.create_unique_constraint(
        "uq_generated_contents_id_tenant",
        "generated_contents",
        ["id", "tenant_id"],
    )


def _create_composite_foreign_keys() -> None:
    op.create_foreign_key(
        "fk_prices_product_tenant",
        "prices",
        "products",
        ["product_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_market_events_previous_snapshot_tenant",
        "market_events",
        "price_snapshots",
        ["previous_snapshot_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_market_events_current_snapshot_tenant",
        "market_events",
        "price_snapshots",
        ["current_snapshot_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_generated_contents_event_tenant",
        "generated_contents",
        "market_events",
        ["event_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_generated_contents_parent_tenant",
        "generated_contents",
        "generated_contents",
        ["parent_content_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_publications_event_tenant",
        "publications",
        "market_events",
        ["event_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_publications_content_tenant",
        "publications",
        "generated_contents",
        ["content_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="RESTRICT",
    )


def _create_optional_parent_triggers() -> None:
    op.execute(
        sa.text(
            """
            CREATE FUNCTION enforce_offer_canonical_product_tenant()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF NEW.canonical_product_id IS NOT NULL
                   AND NOT EXISTS (
                       SELECT 1
                       FROM canonical_products
                       WHERE id = NEW.canonical_product_id
                         AND tenant_id = NEW.tenant_id
                   )
                THEN
                    RAISE EXCEPTION
                        'offer canonical product belongs to another tenant'
                        USING ERRCODE = '23503';
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_offers_canonical_product_tenant
            BEFORE INSERT OR UPDATE OF canonical_product_id, tenant_id
            ON offers
            FOR EACH ROW
            EXECUTE FUNCTION enforce_offer_canonical_product_tenant()
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION enforce_event_canonical_product_tenant()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF NEW.canonical_product_id IS NOT NULL
                   AND NOT EXISTS (
                       SELECT 1
                       FROM canonical_products
                       WHERE id = NEW.canonical_product_id
                         AND tenant_id = NEW.tenant_id
                   )
                THEN
                    RAISE EXCEPTION
                        'event canonical product belongs to another tenant'
                        USING ERRCODE = '23503';
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_market_events_canonical_product_tenant
            BEFORE INSERT OR UPDATE OF canonical_product_id, tenant_id
            ON market_events
            FOR EACH ROW
            EXECUTE FUNCTION enforce_event_canonical_product_tenant()
            """
        )
    )


def _drop_optional_parent_triggers() -> None:
    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS trg_market_events_canonical_product_tenant "
            "ON market_events"
        )
    )
    op.execute(sa.text("DROP FUNCTION IF EXISTS enforce_event_canonical_product_tenant"))
    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS trg_offers_canonical_product_tenant ON offers"
        )
    )
    op.execute(sa.text("DROP FUNCTION IF EXISTS enforce_offer_canonical_product_tenant"))


def _drop_composite_foreign_keys() -> None:
    constraints = (
        ("fk_publications_content_tenant", "publications"),
        ("fk_publications_event_tenant", "publications"),
        ("fk_generated_contents_parent_tenant", "generated_contents"),
        ("fk_generated_contents_event_tenant", "generated_contents"),
        ("fk_market_events_current_snapshot_tenant", "market_events"),
        ("fk_market_events_previous_snapshot_tenant", "market_events"),
        ("fk_prices_product_tenant", "prices"),
    )
    for name, table_name in constraints:
        op.drop_constraint(name, table_name, type_="foreignkey")


def _drop_parent_identities() -> None:
    constraints = (
        ("uq_generated_contents_id_tenant", "generated_contents"),
        ("uq_market_events_id_tenant", "market_events"),
        ("uq_price_snapshots_id_tenant", "price_snapshots"),
        ("uq_canonical_products_id_tenant", "canonical_products"),
        ("uq_products_id_tenant", "products"),
    )
    for name, table_name in constraints:
        op.drop_constraint(name, table_name, type_="unique")
