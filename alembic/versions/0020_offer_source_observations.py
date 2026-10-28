"""Source-scoped marketplace offer availability.

Revision ID: 0020_offer_source_observations
Revises: 0019_diagnostic_incidents
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0020_offer_source_observations"
down_revision = "0019_diagnostic_incidents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add durable source observations and backfill unambiguous legacy rows."""
    op.create_unique_constraint(
        "uq_offers_tenant_id_id",
        "offers",
        ["tenant_id", "id"],
    )
    op.create_table(
        "offer_source_observations",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("integration_id", sa.Uuid(), nullable=False),
        sa.Column("offer_id", sa.Uuid(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("unavailable_since", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "first_seen_at <= last_seen_at AND last_seen_at <= state_updated_at",
            name="ck_offer_source_observations_time_order",
        ),
        sa.CheckConstraint(
            "(is_active AND unavailable_since IS NULL) OR "
            "(NOT is_active AND unavailable_since = state_updated_at)",
            name="ck_offer_source_observations_state",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "integration_id"],
            ["marketplace_integrations.tenant_id", "marketplace_integrations.id"],
            name="fk_offer_source_observations_integration",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "offer_id"],
            ["offers.tenant_id", "offers.id"],
            name="fk_offer_source_observations_offer",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "integration_id",
            "offer_id",
            name="pk_offer_source_observations",
        ),
    )
    op.create_index(
        "ix_offer_source_observations_integration_state",
        "offer_source_observations",
        [
            "tenant_id",
            "integration_id",
            "is_active",
            "state_updated_at",
        ],
    )
    op.create_index(
        "ix_offer_source_observations_active_offer",
        "offer_source_observations",
        ["tenant_id", "offer_id"],
        postgresql_where=sa.text("is_active"),
    )

    op.execute(
        sa.text(
            """
            INSERT INTO offer_source_observations (
                tenant_id,
                integration_id,
                offer_id,
                first_seen_at,
                last_seen_at,
                state_updated_at,
                is_active,
                unavailable_since
            )
            SELECT
                offers.tenant_id,
                integrations.id,
                offers.id,
                offers.created_at,
                offers.created_at,
                offers.created_at,
                true,
                NULL
            FROM offers
            JOIN marketplace_integrations AS integrations
              ON integrations.tenant_id = offers.tenant_id
             AND integrations.marketplace = offers.marketplace
            WHERE offers.external_id IS NOT NULL
              AND (
                  SELECT count(*)
                  FROM marketplace_integrations AS candidates
                  WHERE candidates.tenant_id = offers.tenant_id
                    AND candidates.marketplace = offers.marketplace
              ) = 1
            """
        )
    )


def downgrade() -> None:
    """Remove source observations and restore the previous offer schema."""
    op.drop_table("offer_source_observations")
    op.drop_constraint(
        "uq_offers_tenant_id_id",
        "offers",
        type_="unique",
    )
