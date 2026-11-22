"""Permit immutable activation-condition review actions.

Revision ID: 0028_offer_activation_audit
Revises: 0027_offer_activation_conditions
"""

from __future__ import annotations

from alembic import op

revision = "0028_offer_activation_audit"
down_revision = "0027_offer_activation_conditions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Extend the existing journal without modifying offers or prior audits."""
    _replace_constraint(include_activation=True)
    op.execute("""
        CREATE FUNCTION protect_offer_activation_audit() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.action = 'set_offer_activation_conditions' THEN
                RAISE EXCEPTION 'Activation review audit is append-only'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_offer_activation_audit_immutable
        BEFORE UPDATE OR DELETE ON admin_actions
        FOR EACH ROW EXECUTE FUNCTION protect_offer_activation_audit()
    """)


def downgrade() -> None:
    """Keep retained activation audits from being silently discarded."""
    _replace_constraint(include_activation=False)
    op.execute("DROP TRIGGER trg_offer_activation_audit_immutable ON admin_actions")
    op.execute("DROP FUNCTION protect_offer_activation_audit()")


def _replace_constraint(*, include_activation: bool) -> None:
    actions = (
        "'approve_content', 'reject_content', 'retry_publication', "
        "'cancel_publication', 'resolve_publication_delivered', "
        "'resolve_publication_not_delivered', 'resolve_publication_cancelled', "
        "'retire_offer', 'restore_offer', 'import_catalog_promotion', "
        "'change_product_category'"
    )
    if include_activation:
        actions += ", 'set_offer_activation_conditions'"
    op.drop_constraint("ck_admin_actions_action", "admin_actions", type_="check")
    op.create_check_constraint(
        "ck_admin_actions_action", "admin_actions", f"action IN ({actions})"
    )
