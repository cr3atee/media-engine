"""Sanitized operational diagnostic incident journal.

Revision ID: 0019_diagnostic_incidents
Revises: 0018_product_roles
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0019_diagnostic_incidents"
down_revision = "0018_product_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the bounded, deduplicated operational incident aggregate."""
    op.create_table(
        "diagnostic_incidents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("component", sa.String(64), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("route", sa.String(255), nullable=False),
        sa.Column("method", sa.String(16), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("error_type", sa.String(128), nullable=True),
        sa.Column("environment", sa.String(64), nullable=False),
        sa.Column("release", sa.String(128), nullable=False),
        sa.Column("first_request_id", sa.String(128), nullable=False),
        sa.Column("last_request_id", sa.String(128), nullable=False),
        sa.Column("stack_frames", postgresql.JSONB(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "source IN ('backend', 'frontend')",
            name="ck_diagnostic_incidents_source",
        ),
        sa.CheckConstraint(
            "severity IN ('warning', 'error', 'critical')",
            name="ck_diagnostic_incidents_severity",
        ),
        sa.CheckConstraint(
            "occurrence_count >= 1 AND last_seen_at >= first_seen_at",
            name="ck_diagnostic_incidents_aggregate",
        ),
        sa.CheckConstraint(
            "status_code IS NULL OR status_code BETWEEN 100 AND 599",
            name="ck_diagnostic_incidents_status",
        ),
        sa.CheckConstraint(
            "position('?' in route) = 0",
            name="ck_diagnostic_incidents_route",
        ),
    )
    op.create_index(
        "uq_diagnostic_incidents_fingerprint",
        "diagnostic_incidents",
        ["fingerprint"],
        unique=True,
    )
    op.create_index(
        "ix_diagnostic_incidents_last_seen",
        "diagnostic_incidents",
        ["last_seen_at", "id"],
    )
    op.create_index(
        "ix_diagnostic_incidents_severity_time",
        "diagnostic_incidents",
        ["severity", "last_seen_at"],
    )
    op.create_index(
        "ix_diagnostic_incidents_component_time",
        "diagnostic_incidents",
        ["component", "last_seen_at"],
    )
    op.create_index(
        "ix_diagnostic_incidents_tenant_time",
        "diagnostic_incidents",
        ["tenant_id", "last_seen_at"],
    )


def downgrade() -> None:
    """Remove the diagnostic journal without touching business records."""
    op.drop_table("diagnostic_incidents")
