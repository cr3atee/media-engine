"""create generated content and publications

Revision ID: 0008_content_publications
Revises: 0007_create_market_events
Create Date: 2026-07-29 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0008_content_publications"
down_revision = "0007_create_market_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generated_contents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("parent_content_id", sa.Uuid(), nullable=True),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=128), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("generation_status", sa.String(length=32), nullable=False),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.CHAR(length=64), nullable=False),
        sa.Column("content_checksum", sa.CHAR(length=64), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("worker_id", sa.String(length=255), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
        sa.Column("last_error_summary", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "attempt_number >= 1",
            name="ck_generated_contents_attempt_number",
        ),
        sa.CheckConstraint(
            "(generation_status = 'in_progress' "
            "AND claim_token IS NOT NULL "
            "AND worker_id IS NOT NULL "
            "AND claimed_at IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR "
            "(generation_status <> 'in_progress' "
            "AND claim_token IS NULL "
            "AND worker_id IS NULL "
            "AND claimed_at IS NULL "
            "AND lease_expires_at IS NULL)",
            name="ck_generated_contents_claim_state",
        ),
        sa.CheckConstraint(
            "generation_status <> 'failed' OR "
            "(last_error_code IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_generated_contents_failed_payload",
        ),
        sa.CheckConstraint(
            "generation_status IN "
            "('pending', 'in_progress', 'generated', 'failed', 'abandoned')",
            name="ck_generated_contents_generation_status",
        ),
        sa.CheckConstraint(
            "(last_error_code IS NULL) = (last_error_summary IS NULL)",
            name="ck_generated_contents_last_error_pair",
        ),
        sa.CheckConstraint(
            "lease_expires_at IS NULL OR lease_expires_at > claimed_at",
            name="ck_generated_contents_lease_window",
        ),
        sa.CheckConstraint(
            "origin IN ('ai', 'human_edit')",
            name="ck_generated_contents_origin",
        ),
        sa.CheckConstraint(
            "review_status IN ('not_required', 'pending', 'approved', 'rejected')",
            name="ck_generated_contents_review_status",
        ),
        sa.CheckConstraint(
            "(generation_status = 'generated' "
            "AND content_text IS NOT NULL "
            "AND btrim(content_text) <> '' "
            "AND content_checksum IS NOT NULL "
            "AND completed_at IS NOT NULL) OR "
            "(generation_status <> 'generated' AND content_checksum IS NULL)",
            name="ck_generated_contents_terminal_payload",
        ),
        sa.CheckConstraint(
            "updated_at >= created_at AND "
            "(completed_at IS NULL OR completed_at >= created_at)",
            name="ck_generated_contents_timestamp_order",
        ),
        sa.CheckConstraint("version >= 1", name="ck_generated_contents_version"),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["market_events.id"],
            name="fk_generated_contents_event",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_content_id"],
            ["generated_contents.id"],
            name="fk_generated_contents_parent",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_generated_contents"),
        sa.UniqueConstraint(
            "event_id",
            "content_type",
            "language",
            "prompt_version",
            "attempt_number",
            name="uq_generated_contents_event_attempt",
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_generated_contents_idempotency_key",
        ),
    )
    op.create_index(
        "ix_generated_contents_claim",
        "generated_contents",
        ["generation_status", "next_retry_at", "created_at", "id"],
        unique=False,
        postgresql_where=sa.text("generation_status IN ('pending', 'failed')"),
    )
    op.create_index(
        "ix_generated_contents_event_created",
        "generated_contents",
        ["event_id", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_generated_contents_lease_expiry",
        "generated_contents",
        ["lease_expires_at", "created_at", "id"],
        unique=False,
        postgresql_where=sa.text("generation_status = 'in_progress'"),
    )
    op.create_index(
        "ix_generated_contents_review",
        "generated_contents",
        ["review_status", "created_at"],
        unique=False,
        postgresql_where=sa.text("review_status = 'pending'"),
    )
    op.create_index(
        "uq_generated_contents_active_generation",
        "generated_contents",
        ["event_id", "content_type", "language", "prompt_version"],
        unique=True,
        postgresql_where=sa.text("generation_status IN ('pending', 'in_progress')"),
    )

    op.create_table(
        "publications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("content_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=64), nullable=False),
        sa.Column("destination_key", sa.String(length=255), nullable=False),
        sa.Column("publication_status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.CHAR(length=64), nullable=False),
        sa.Column("external_message_id", sa.String(length=255), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("worker_id", sa.String(length=255), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
        sa.Column("last_error_summary", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_publications_attempt_count",
        ),
        sa.CheckConstraint(
            "(publication_status = 'in_progress' "
            "AND claim_token IS NOT NULL "
            "AND worker_id IS NOT NULL "
            "AND claimed_at IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR "
            "(publication_status <> 'in_progress' "
            "AND claim_token IS NULL "
            "AND worker_id IS NULL "
            "AND claimed_at IS NULL "
            "AND lease_expires_at IS NULL)",
            name="ck_publications_claim_state",
        ),
        sa.CheckConstraint(
            "publication_status NOT IN ('failed', 'ambiguous') OR "
            "last_error_code IS NOT NULL",
            name="ck_publications_failure_payload",
        ),
        sa.CheckConstraint(
            "(last_error_code IS NULL) = (last_error_summary IS NULL)",
            name="ck_publications_last_error_pair",
        ),
        sa.CheckConstraint(
            "lease_expires_at IS NULL OR lease_expires_at > claimed_at",
            name="ck_publications_lease_window",
        ),
        sa.CheckConstraint(
            "(publication_status = 'published' "
            "AND published_at IS NOT NULL "
            "AND external_message_id IS NOT NULL "
            "AND btrim(external_message_id) <> '') OR "
            "(publication_status <> 'published' "
            "AND published_at IS NULL "
            "AND external_message_id IS NULL)",
            name="ck_publications_published_payload",
        ),
        sa.CheckConstraint(
            "publication_status IN "
            "('pending', 'in_progress', 'published', 'failed', "
            "'ambiguous', 'cancelled')",
            name="ck_publications_status",
        ),
        sa.CheckConstraint(
            "updated_at >= created_at AND "
            "(published_at IS NULL OR published_at >= created_at)",
            name="ck_publications_timestamp_order",
        ),
        sa.CheckConstraint("version >= 1", name="ck_publications_version"),
        sa.ForeignKeyConstraint(
            ["content_id"],
            ["generated_contents.id"],
            name="fk_publications_content",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["market_events.id"],
            name="fk_publications_event",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_publications"),
        sa.UniqueConstraint(
            "content_id",
            "channel",
            "destination_key",
            name="uq_publications_content_channel_destination",
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_publications_idempotency_key",
        ),
    )
    op.create_index(
        "ix_publications_claim",
        "publications",
        [
            "publication_status",
            "scheduled_at",
            "next_retry_at",
            "created_at",
            "id",
        ],
        unique=False,
        postgresql_where=sa.text("publication_status IN ('pending', 'failed')"),
    )
    op.create_index(
        "ix_publications_event_created",
        "publications",
        ["event_id", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_publications_lease_expiry",
        "publications",
        ["lease_expires_at", "created_at", "id"],
        unique=False,
        postgresql_where=sa.text("publication_status = 'in_progress'"),
    )
    op.create_index(
        "ix_publications_status_schedule",
        "publications",
        ["publication_status", "scheduled_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_publications_status_schedule", table_name="publications")
    op.drop_index("ix_publications_lease_expiry", table_name="publications")
    op.drop_index("ix_publications_event_created", table_name="publications")
    op.drop_index("ix_publications_claim", table_name="publications")
    op.drop_table("publications")

    op.drop_index(
        "uq_generated_contents_active_generation",
        table_name="generated_contents",
    )
    op.drop_index("ix_generated_contents_review", table_name="generated_contents")
    op.drop_index(
        "ix_generated_contents_lease_expiry",
        table_name="generated_contents",
    )
    op.drop_index(
        "ix_generated_contents_event_created",
        table_name="generated_contents",
    )
    op.drop_index("ix_generated_contents_claim", table_name="generated_contents")
    op.drop_table("generated_contents")
