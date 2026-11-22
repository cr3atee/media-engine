"""Persist explicit offer activation conditions without inventing legacy terms.

Revision ID: 0027_offer_activation_conditions
Revises: 0026_product_category_audit
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0027_offer_activation_conditions"
down_revision = "0026_product_category_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Keep every pre-existing offer's conditions unknown."""
    op.add_column(
        "offers",
        sa.Column(
            "activation_conditions", postgresql.JSONB(none_as_null=True), nullable=True
        ),
    )


def downgrade() -> None:
    """Remove the optional conditions storage; offer identities stay unchanged."""
    op.drop_column("offers", "activation_conditions")
