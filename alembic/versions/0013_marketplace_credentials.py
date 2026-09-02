"""marketplace credential metadata

Revision ID: 0013_marketplace_credentials
Revises: 0012_marketplace_integrations
Create Date: 2026-09-02 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0013_marketplace_credentials"
down_revision = "0012_marketplace_integrations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "marketplace_integrations",
        sa.Column("credential_reference", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "marketplace_integrations",
        sa.Column(
            "credential_configured_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "marketplace_integrations",
        sa.Column(
            "credential_last_rotated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "marketplace_integrations",
        sa.Column(
            "credential_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.alter_column(
        "marketplace_integrations",
        "credential_version",
        server_default=None,
    )

    op.create_check_constraint(
        "ck_marketplace_integrations_credential_reference_nonempty",
        "marketplace_integrations",
        "credential_reference IS NULL OR length(btrim(credential_reference)) > 0",
    )
    op.create_check_constraint(
        "ck_marketplace_integrations_credential_version",
        "marketplace_integrations",
        "credential_version >= 0",
    )
    op.create_check_constraint(
        "ck_marketplace_integrations_auth_none_without_reference",
        "marketplace_integrations",
        "auth_type <> 'none' OR credential_reference IS NULL",
    )
    op.create_check_constraint(
        "ck_marketplace_integrations_credential_state",
        "marketplace_integrations",
        "("
        "credential_reference IS NULL "
        "AND credential_configured_at IS NULL "
        "AND credential_last_rotated_at IS NULL "
        "AND credential_version = 0"
        ") OR ("
        "credential_reference IS NOT NULL "
        "AND credential_configured_at IS NOT NULL "
        "AND credential_version >= 1"
        ")",
    )
    op.create_check_constraint(
        "ck_marketplace_integrations_credential_rotation_time",
        "marketplace_integrations",
        "credential_last_rotated_at IS NULL "
        "OR credential_last_rotated_at >= credential_configured_at",
    )
    op.create_index(
        "ix_marketplace_integrations_credentials",
        "marketplace_integrations",
        ["tenant_id", "auth_type", "credential_configured_at"],
        postgresql_where=sa.text("credential_reference IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_marketplace_integrations_credentials",
        table_name="marketplace_integrations",
    )
    op.drop_constraint(
        "ck_marketplace_integrations_credential_rotation_time",
        "marketplace_integrations",
        type_="check",
    )
    op.drop_constraint(
        "ck_marketplace_integrations_credential_state",
        "marketplace_integrations",
        type_="check",
    )
    op.drop_constraint(
        "ck_marketplace_integrations_auth_none_without_reference",
        "marketplace_integrations",
        type_="check",
    )
    op.drop_constraint(
        "ck_marketplace_integrations_credential_version",
        "marketplace_integrations",
        type_="check",
    )
    op.drop_constraint(
        "ck_marketplace_integrations_credential_reference_nonempty",
        "marketplace_integrations",
        type_="check",
    )
    op.drop_column("marketplace_integrations", "credential_version")
    op.drop_column("marketplace_integrations", "credential_last_rotated_at")
    op.drop_column("marketplace_integrations", "credential_configured_at")
    op.drop_column("marketplace_integrations", "credential_reference")
