"""Allow catalog promotion imports in the immutable admin audit.

Revision ID: 0025_catalog_promotion_audit
Revises: 0024_offer_catalog_fields
"""

from __future__ import annotations

from alembic import op

revision = "0025_catalog_promotion_audit"
down_revision = "0024_offer_catalog_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Extend admin audit constraints for catalog promotion imports."""
    _replace_constraints(include_catalog_promotion=True)


def downgrade() -> None:
    """Restore the admin audit constraints used before catalog promotion."""
    _replace_constraints(include_catalog_promotion=False)


def _replace_constraints(*, include_catalog_promotion: bool) -> None:
    op.drop_constraint("ck_admin_actions_action", "admin_actions", type_="check")
    op.drop_constraint(
        "ck_admin_actions_resource_type",
        "admin_actions",
        type_="check",
    )

    actions = (
        "'approve_content', 'reject_content', 'retry_publication', "
        "'cancel_publication', 'resolve_publication_delivered', "
        "'resolve_publication_not_delivered', 'resolve_publication_cancelled', "
        "'retire_offer', 'restore_offer'"
    )
    resource_types = "'content', 'publication', 'offer'"
    if include_catalog_promotion:
        actions += ", 'import_catalog_promotion'"
        resource_types += ", 'catalog_promotion'"

    op.create_check_constraint(
        "ck_admin_actions_action",
        "admin_actions",
        f"action IN ({actions})",
    )
    op.create_check_constraint(
        "ck_admin_actions_resource_type",
        "admin_actions",
        f"resource_type IN ({resource_types})",
    )
