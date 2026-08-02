"""create tenant identity foundation

Revision ID: 0010_tenant_foundation
Revises: 0009_admin_actions
Create Date: 2026-08-02 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0010_tenant_foundation"
down_revision = "0009_admin_actions"
branch_labels = None
depends_on = None

LEGACY_TENANT_ID = "00000000-0000-4000-8000-000000000001"
LEGACY_CREATED_AT = "2026-08-02 00:00:00+00"

TENANT_OWNED_TABLES = (
    "products",
    "prices",
    "canonical_products",
    "offers",
    "price_snapshots",
    "market_events",
    "generated_contents",
    "publications",
    "admin_actions",
)


def upgrade() -> None:
    _create_identity_tables()
    _seed_legacy_tenant()
    _add_tenant_columns()
    _backfill_legacy_ownership()
    _enforce_tenant_columns()
    _add_tenant_foreign_keys()
    _replace_global_integrity()


def downgrade() -> None:
    _assert_downgrade_is_safe()
    _restore_global_integrity()
    _drop_tenant_foreign_keys()
    _drop_tenant_columns()
    _drop_identity_tables()


def _create_identity_tables() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_tenants_name_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(slug)) > 0",
            name="ck_tenants_slug_nonempty",
        ),
        sa.CheckConstraint("version >= 1", name="ck_tenants_version"),
        sa.CheckConstraint(
            "updated_at >= created_at",
            name="ck_tenants_timestamp_order",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tenants"),
    )
    op.create_index("uq_tenants_slug", "tenants", ["slug"], unique=True)
    op.create_index("ix_tenants_active", "tenants", ["is_active"], unique=False)

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "length(btrim(email)) > 0",
            name="ck_users_email_nonempty",
        ),
        sa.CheckConstraint("version >= 1", name="ck_users_version"),
        sa.CheckConstraint(
            "updated_at >= created_at",
            name="ck_users_timestamp_order",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_index("uq_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_enabled", "users", ["enabled"], unique=False)

    op.create_table(
        "tenant_memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "role IN ('owner', 'administrator', 'reviewer', 'operator', 'viewer')",
            name="ck_tenant_memberships_role",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_tenant_memberships_version",
        ),
        sa.CheckConstraint(
            "updated_at >= joined_at",
            name="ck_tenant_memberships_timestamp_order",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_tenant_memberships_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_tenant_memberships_user",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tenant_memberships"),
        sa.UniqueConstraint(
            "user_id",
            "tenant_id",
            name="uq_tenant_memberships_user_tenant",
        ),
    )
    op.create_index(
        "ix_tenant_memberships_user",
        "tenant_memberships",
        ["user_id", "is_active"],
        unique=False,
    )
    op.create_index(
        "ix_tenant_memberships_tenant",
        "tenant_memberships",
        ["tenant_id", "is_active"],
        unique=False,
    )
    op.create_index(
        "ix_tenant_memberships_role",
        "tenant_memberships",
        ["tenant_id", "role"],
        unique=False,
    )


def _seed_legacy_tenant() -> None:
    op.execute(
        sa.text(
            f"""
            INSERT INTO tenants (
                id, name, slug, is_active, created_at, updated_at, version
            ) VALUES (
                '{LEGACY_TENANT_ID}'::uuid,
                'Legacy Tenant',
                'legacy',
                TRUE,
                '{LEGACY_CREATED_AT}'::timestamptz,
                '{LEGACY_CREATED_AT}'::timestamptz,
                1
            )
            """
        )
    )


def _add_tenant_columns() -> None:
    for table_name in TENANT_OWNED_TABLES:
        op.add_column(
            table_name,
            sa.Column("tenant_id", sa.Uuid(), nullable=True),
        )

    op.add_column(
        "admin_actions",
        sa.Column("actor_type", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "admin_actions",
        sa.Column("elevated", sa.Boolean(), nullable=True),
    )


def _backfill_legacy_ownership() -> None:
    for table_name in TENANT_OWNED_TABLES:
        op.execute(
            sa.text(
                f"UPDATE {table_name} "
                f"SET tenant_id = '{LEGACY_TENANT_ID}'::uuid "
                "WHERE tenant_id IS NULL"
            )
        )

    op.execute(
        sa.text(
            "UPDATE admin_actions SET actor_type = 'api_key' WHERE actor_type IS NULL"
        )
    )
    op.execute(
        sa.text("UPDATE admin_actions SET elevated = FALSE WHERE elevated IS NULL")
    )


def _enforce_tenant_columns() -> None:
    for table_name in TENANT_OWNED_TABLES:
        op.alter_column(
            table_name,
            "tenant_id",
            existing_type=sa.Uuid(),
            nullable=False,
        )

    op.alter_column(
        "admin_actions",
        "actor_type",
        existing_type=sa.String(length=32),
        nullable=False,
    )
    op.alter_column(
        "admin_actions",
        "elevated",
        existing_type=sa.Boolean(),
        nullable=False,
    )
    op.create_check_constraint(
        "ck_admin_actions_actor_type",
        "admin_actions",
        "actor_type IN "
        "('api_key', 'platform_admin', 'user', 'system', 'worker', 'migration')",
    )


def _add_tenant_foreign_keys() -> None:
    foreign_keys = (
        ("fk_products_tenant_id_tenants", "products", None),
        ("fk_prices_tenant_id_tenants", "prices", None),
        (
            "fk_canonical_products_tenant_id_tenants",
            "canonical_products",
            "RESTRICT",
        ),
        ("fk_offers_tenant_id_tenants", "offers", "RESTRICT"),
        (
            "fk_price_snapshots_tenant_id_tenants",
            "price_snapshots",
            "RESTRICT",
        ),
        ("fk_market_events_tenant", "market_events", "RESTRICT"),
        ("fk_generated_contents_tenant", "generated_contents", "RESTRICT"),
        ("fk_publications_tenant", "publications", "RESTRICT"),
        ("fk_admin_actions_tenant", "admin_actions", "RESTRICT"),
    )
    for name, source_table, ondelete in foreign_keys:
        op.create_foreign_key(
            name,
            source_table,
            "tenants",
            ["tenant_id"],
            ["id"],
            ondelete=ondelete,
        )


def _replace_global_integrity() -> None:
    op.create_index(
        "uq_products_tenant_marketplace_external_id",
        "products",
        ["tenant_id", "marketplace_id", "external_id"],
        unique=True,
    )
    op.create_index(
        "ix_prices_tenant_product_collected",
        "prices",
        ["tenant_id", "product_id", "collected_at"],
        unique=False,
    )
    op.create_index(
        "ix_canonical_products_tenant_name",
        "canonical_products",
        ["tenant_id", "name"],
        unique=False,
    )

    op.drop_index(
        "uq_offers_marketplace_external_id_not_null",
        table_name="offers",
    )
    op.create_index(
        "uq_offers_marketplace_external_id_not_null",
        "offers",
        ["tenant_id", "marketplace", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )
    op.create_index(
        "ix_offers_tenant_created",
        "offers",
        ["tenant_id", "created_at", "id"],
        unique=False,
    )

    op.drop_index(
        "ix_price_snapshots_history_order",
        table_name="price_snapshots",
    )
    op.drop_constraint(
        "uq_price_snapshots_exact_identity",
        "price_snapshots",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_price_snapshots_exact_identity",
        "price_snapshots",
        [
            "tenant_id",
            "marketplace",
            "external_id",
            "collected_at",
            "price",
            "currency",
        ],
    )
    op.create_index(
        "ix_price_snapshots_history_order",
        "price_snapshots",
        ["tenant_id", "marketplace", "external_id", "collected_at", "id"],
        unique=False,
    )

    op.drop_index("ix_market_events_canonical_timeline", table_name="market_events")
    op.drop_index("ix_market_events_offer_timeline", table_name="market_events")
    op.drop_index("uq_market_events_snapshot_transition", table_name="market_events")
    op.drop_constraint(
        "uq_market_events_identity_key",
        "market_events",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_market_events_identity_key",
        "market_events",
        ["tenant_id", "identity_key"],
    )
    op.create_index(
        "uq_market_events_snapshot_transition",
        "market_events",
        [
            "tenant_id",
            "event_type",
            "previous_snapshot_id",
            "current_snapshot_id",
        ],
        unique=True,
        postgresql_where=sa.text(
            "previous_snapshot_id IS NOT NULL AND current_snapshot_id IS NOT NULL"
        ),
    )
    op.create_index(
        "ix_market_events_offer_timeline",
        "market_events",
        [
            "tenant_id",
            "marketplace",
            "external_id",
            sa.text("occurred_at DESC"),
        ],
        unique=False,
    )
    op.create_index(
        "ix_market_events_canonical_timeline",
        "market_events",
        ["tenant_id", "canonical_product_id", sa.text("occurred_at DESC")],
        unique=False,
        postgresql_where=sa.text("canonical_product_id IS NOT NULL"),
    )

    op.drop_index(
        "uq_generated_contents_active_generation",
        table_name="generated_contents",
    )
    op.drop_index(
        "ix_generated_contents_event_created",
        table_name="generated_contents",
    )
    op.drop_constraint(
        "uq_generated_contents_event_attempt",
        "generated_contents",
        type_="unique",
    )
    op.drop_constraint(
        "uq_generated_contents_idempotency_key",
        "generated_contents",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_generated_contents_idempotency_key",
        "generated_contents",
        ["tenant_id", "idempotency_key"],
    )
    op.create_unique_constraint(
        "uq_generated_contents_event_attempt",
        "generated_contents",
        [
            "tenant_id",
            "event_id",
            "content_type",
            "language",
            "prompt_version",
            "attempt_number",
        ],
    )
    op.create_index(
        "uq_generated_contents_active_generation",
        "generated_contents",
        ["tenant_id", "event_id", "content_type", "language", "prompt_version"],
        unique=True,
        postgresql_where=sa.text("generation_status IN ('pending', 'in_progress')"),
    )
    op.create_index(
        "ix_generated_contents_event_created",
        "generated_contents",
        ["tenant_id", "event_id", sa.text("created_at DESC")],
        unique=False,
    )

    op.drop_index("ix_publications_status_schedule", table_name="publications")
    op.drop_index("ix_publications_event_created", table_name="publications")
    op.drop_constraint(
        "uq_publications_content_channel_destination",
        "publications",
        type_="unique",
    )
    op.drop_constraint(
        "uq_publications_idempotency_key",
        "publications",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_publications_idempotency_key",
        "publications",
        ["tenant_id", "idempotency_key"],
    )
    op.create_unique_constraint(
        "uq_publications_content_channel_destination",
        "publications",
        ["tenant_id", "content_id", "channel", "destination_key"],
    )
    op.create_index(
        "ix_publications_event_created",
        "publications",
        ["tenant_id", "event_id", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_publications_status_schedule",
        "publications",
        ["tenant_id", "publication_status", "scheduled_at"],
        unique=False,
    )

    for index_name in (
        "ix_admin_actions_resource_created",
        "ix_admin_actions_request_id",
        "ix_admin_actions_created",
        "ix_admin_actions_actor_created",
    ):
        op.drop_index(index_name, table_name="admin_actions")
    op.drop_constraint(
        "uq_admin_actions_idempotency_key",
        "admin_actions",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_admin_actions_idempotency_key",
        "admin_actions",
        ["tenant_id", "idempotency_key"],
    )
    op.create_index(
        "ix_admin_actions_resource_created",
        "admin_actions",
        [
            "tenant_id",
            "resource_type",
            "resource_id",
            sa.text("created_at DESC"),
            sa.text("id DESC"),
        ],
        unique=False,
    )
    op.create_index(
        "ix_admin_actions_actor_created",
        "admin_actions",
        [
            "tenant_id",
            "actor_id",
            sa.text("created_at DESC"),
            sa.text("id DESC"),
        ],
        unique=False,
    )
    op.create_index(
        "ix_admin_actions_request_id",
        "admin_actions",
        ["tenant_id", "request_id", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_admin_actions_created",
        "admin_actions",
        ["tenant_id", sa.text("created_at DESC"), sa.text("id DESC")],
        unique=False,
    )


def _assert_downgrade_is_safe() -> None:
    table_checks = " OR ".join(
        f"EXISTS (SELECT 1 FROM {table} WHERE tenant_id <> '{LEGACY_TENANT_ID}'::uuid)"
        for table in TENANT_OWNED_TABLES
    )
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM users)
                    OR EXISTS (SELECT 1 FROM tenant_memberships)
                    OR EXISTS (
                        SELECT 1 FROM tenants
                        WHERE id <> '{LEGACY_TENANT_ID}'::uuid
                    )
                    OR {table_checks}
                THEN
                    RAISE EXCEPTION
                        'Cannot downgrade tenant foundation with tenant data'
                        USING HINT = 'Remove non-legacy tenant data first';
                END IF;
            END
            $$;
            """
        )
    )


def _restore_global_integrity() -> None:
    op.drop_index("ix_admin_actions_created", table_name="admin_actions")
    op.drop_index("ix_admin_actions_request_id", table_name="admin_actions")
    op.drop_index("ix_admin_actions_actor_created", table_name="admin_actions")
    op.drop_index("ix_admin_actions_resource_created", table_name="admin_actions")
    op.drop_constraint(
        "uq_admin_actions_idempotency_key",
        "admin_actions",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_admin_actions_idempotency_key",
        "admin_actions",
        ["idempotency_key"],
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

    op.drop_index("ix_publications_status_schedule", table_name="publications")
    op.drop_index("ix_publications_event_created", table_name="publications")
    op.drop_constraint(
        "uq_publications_content_channel_destination",
        "publications",
        type_="unique",
    )
    op.drop_constraint(
        "uq_publications_idempotency_key",
        "publications",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_publications_idempotency_key",
        "publications",
        ["idempotency_key"],
    )
    op.create_unique_constraint(
        "uq_publications_content_channel_destination",
        "publications",
        ["content_id", "channel", "destination_key"],
    )
    op.create_index(
        "ix_publications_event_created",
        "publications",
        ["event_id", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_publications_status_schedule",
        "publications",
        ["publication_status", "scheduled_at"],
        unique=False,
    )

    op.drop_index(
        "uq_generated_contents_active_generation",
        table_name="generated_contents",
    )
    op.drop_index(
        "ix_generated_contents_event_created",
        table_name="generated_contents",
    )
    op.drop_constraint(
        "uq_generated_contents_event_attempt",
        "generated_contents",
        type_="unique",
    )
    op.drop_constraint(
        "uq_generated_contents_idempotency_key",
        "generated_contents",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_generated_contents_idempotency_key",
        "generated_contents",
        ["idempotency_key"],
    )
    op.create_unique_constraint(
        "uq_generated_contents_event_attempt",
        "generated_contents",
        [
            "event_id",
            "content_type",
            "language",
            "prompt_version",
            "attempt_number",
        ],
    )
    op.create_index(
        "uq_generated_contents_active_generation",
        "generated_contents",
        ["event_id", "content_type", "language", "prompt_version"],
        unique=True,
        postgresql_where=sa.text("generation_status IN ('pending', 'in_progress')"),
    )
    op.create_index(
        "ix_generated_contents_event_created",
        "generated_contents",
        ["event_id", sa.text("created_at DESC")],
        unique=False,
    )

    op.drop_index("ix_market_events_canonical_timeline", table_name="market_events")
    op.drop_index("ix_market_events_offer_timeline", table_name="market_events")
    op.drop_index("uq_market_events_snapshot_transition", table_name="market_events")
    op.drop_constraint(
        "uq_market_events_identity_key",
        "market_events",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_market_events_identity_key",
        "market_events",
        ["identity_key"],
    )
    op.create_index(
        "uq_market_events_snapshot_transition",
        "market_events",
        ["event_type", "previous_snapshot_id", "current_snapshot_id"],
        unique=True,
        postgresql_where=sa.text(
            "previous_snapshot_id IS NOT NULL AND current_snapshot_id IS NOT NULL"
        ),
    )
    op.create_index(
        "ix_market_events_offer_timeline",
        "market_events",
        ["marketplace", "external_id", sa.text("occurred_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_market_events_canonical_timeline",
        "market_events",
        ["canonical_product_id", sa.text("occurred_at DESC")],
        unique=False,
        postgresql_where=sa.text("canonical_product_id IS NOT NULL"),
    )

    op.drop_index(
        "ix_price_snapshots_history_order",
        table_name="price_snapshots",
    )
    op.drop_constraint(
        "uq_price_snapshots_exact_identity",
        "price_snapshots",
        type_="unique",
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

    op.drop_index("ix_offers_tenant_created", table_name="offers")
    op.drop_index(
        "uq_offers_marketplace_external_id_not_null",
        table_name="offers",
    )
    op.create_index(
        "uq_offers_marketplace_external_id_not_null",
        "offers",
        ["marketplace", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )

    op.drop_index(
        "ix_canonical_products_tenant_name",
        table_name="canonical_products",
    )
    op.drop_index("ix_prices_tenant_product_collected", table_name="prices")
    op.drop_index(
        "uq_products_tenant_marketplace_external_id",
        table_name="products",
    )


def _drop_tenant_foreign_keys() -> None:
    foreign_keys = (
        ("fk_admin_actions_tenant", "admin_actions"),
        ("fk_publications_tenant", "publications"),
        ("fk_generated_contents_tenant", "generated_contents"),
        ("fk_market_events_tenant", "market_events"),
        ("fk_price_snapshots_tenant_id_tenants", "price_snapshots"),
        ("fk_offers_tenant_id_tenants", "offers"),
        ("fk_canonical_products_tenant_id_tenants", "canonical_products"),
        ("fk_prices_tenant_id_tenants", "prices"),
        ("fk_products_tenant_id_tenants", "products"),
    )
    for name, source_table in foreign_keys:
        op.drop_constraint(name, source_table, type_="foreignkey")


def _drop_tenant_columns() -> None:
    op.drop_constraint(
        "ck_admin_actions_actor_type",
        "admin_actions",
        type_="check",
    )
    op.drop_column("admin_actions", "elevated")
    op.drop_column("admin_actions", "actor_type")

    for table_name in reversed(TENANT_OWNED_TABLES):
        op.drop_column(table_name, "tenant_id")


def _drop_identity_tables() -> None:
    op.drop_index(
        "ix_tenant_memberships_role",
        table_name="tenant_memberships",
    )
    op.drop_index(
        "ix_tenant_memberships_tenant",
        table_name="tenant_memberships",
    )
    op.drop_index(
        "ix_tenant_memberships_user",
        table_name="tenant_memberships",
    )
    op.drop_table("tenant_memberships")

    op.drop_index("ix_users_enabled", table_name="users")
    op.drop_index("uq_users_email", table_name="users")
    op.drop_table("users")

    op.drop_index("ix_tenants_active", table_name="tenants")
    op.drop_index("uq_tenants_slug", table_name="tenants")
    op.drop_table("tenants")
