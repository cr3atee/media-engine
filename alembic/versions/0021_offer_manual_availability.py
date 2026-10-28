"""Operator-controlled offer availability with immutable audit support.

Revision ID: 0021_offer_manual_availability
Revises: 0020_offer_source_observations
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0021_offer_manual_availability"
down_revision = "0020_offer_source_observations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add reversible manual offer state and expand admin audit enums."""
    op.add_column(
        "offers",
        sa.Column(
            "manual_availability_status",
            sa.String(length=16),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
    )
    op.add_column(
        "offers",
        sa.Column(
            "manual_availability_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.add_column(
        "offers",
        sa.Column(
            "manual_availability_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "offers",
        sa.Column("manually_retired_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE offers SET manual_availability_updated_at = created_at "
            "WHERE manual_availability_updated_at IS NULL"
        )
    )
    op.alter_column(
        "offers",
        "manual_availability_updated_at",
        nullable=False,
    )
    op.create_check_constraint(
        "ck_offers_manual_availability_status",
        "offers",
        "manual_availability_status IN ('active', 'retired')",
    )
    op.create_check_constraint(
        "ck_offers_manual_availability_version",
        "offers",
        "manual_availability_version >= 1",
    )
    op.create_check_constraint(
        "ck_offers_manual_availability_state",
        "offers",
        "(manual_availability_status = 'active' AND manually_retired_at IS NULL) "
        "OR (manual_availability_status = 'retired' "
        "AND manually_retired_at IS NOT NULL)",
    )
    op.create_index(
        "ix_offers_tenant_manual_active_created",
        "offers",
        ["tenant_id", "created_at", "id"],
        postgresql_where=sa.text("manual_availability_status = 'active'"),
    )

    op.drop_constraint("ck_admin_actions_action", "admin_actions", type_="check")
    op.drop_constraint(
        "ck_admin_actions_resource_type",
        "admin_actions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_admin_actions_action",
        "admin_actions",
        "action IN ('approve_content', 'reject_content', 'retry_publication', "
        "'cancel_publication', 'resolve_publication_delivered', "
        "'resolve_publication_not_delivered', 'resolve_publication_cancelled', "
        "'retire_offer', 'restore_offer')",
    )
    op.create_check_constraint(
        "ck_admin_actions_resource_type",
        "admin_actions",
        "resource_type IN ('content', 'publication', 'offer')",
    )


def downgrade() -> None:
    """Remove manual offer state and restore previous audit constraints."""
    op.drop_constraint("ck_admin_actions_action", "admin_actions", type_="check")
    op.drop_constraint(
        "ck_admin_actions_resource_type",
        "admin_actions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_admin_actions_action",
        "admin_actions",
        "action IN ('approve_content', 'reject_content', 'retry_publication', "
        "'cancel_publication', 'resolve_publication_delivered', "
        "'resolve_publication_not_delivered', 'resolve_publication_cancelled')",
    )
    op.create_check_constraint(
        "ck_admin_actions_resource_type",
        "admin_actions",
        "resource_type IN ('content', 'publication')",
    )

    op.drop_index("ix_offers_tenant_manual_active_created", table_name="offers")
    op.drop_constraint(
        "ck_offers_manual_availability_state",
        "offers",
        type_="check",
    )
    op.drop_constraint(
        "ck_offers_manual_availability_version",
        "offers",
        type_="check",
    )
    op.drop_constraint(
        "ck_offers_manual_availability_status",
        "offers",
        type_="check",
    )
    op.drop_column("offers", "manually_retired_at")
    op.drop_column("offers", "manual_availability_updated_at")
    op.drop_column("offers", "manual_availability_version")
    op.drop_column("offers", "manual_availability_status")
