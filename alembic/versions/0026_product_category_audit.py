"""Allow audited canonical product category corrections.

Revision ID: 0026_product_category_audit
Revises: 0025_catalog_promotion_audit
"""

from __future__ import annotations

from alembic import op

revision = "0026_product_category_audit"
down_revision = "0025_catalog_promotion_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Permit category correction audit rows without modifying existing data."""
    _replace_constraints(include_category_changes=True)


def downgrade() -> None:
    """Restore old constraints; retained category audits block unsafe downgrade."""
    _replace_constraints(include_category_changes=False)


def _replace_constraints(*, include_category_changes: bool) -> None:
    actions = (
        "'approve_content', 'reject_content', 'retry_publication', "
        "'cancel_publication', 'resolve_publication_delivered', "
        "'resolve_publication_not_delivered', 'resolve_publication_cancelled', "
        "'retire_offer', 'restore_offer', 'import_catalog_promotion'"
    )
    resources = "'content', 'publication', 'offer', 'catalog_promotion'"
    if include_category_changes:
        actions += ", 'change_product_category'"
        resources += ", 'canonical_product'"
    op.drop_constraint("ck_admin_actions_action", "admin_actions", type_="check")
    op.drop_constraint("ck_admin_actions_resource_type", "admin_actions", type_="check")
    op.create_check_constraint(
        "ck_admin_actions_action", "admin_actions", f"action IN ({actions})"
    )
    op.create_check_constraint(
        "ck_admin_actions_resource_type",
        "admin_actions",
        f"resource_type IN ({resources})",
    )
