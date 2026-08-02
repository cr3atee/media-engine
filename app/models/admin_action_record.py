from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.domain.tenancy import LEGACY_TENANT_ID


class AdminActionRecord(Base):
    """Append-only SQLAlchemy record for accepted admin commands."""

    __tablename__ = "admin_actions"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_admin_actions"),
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_admin_actions_idempotency_key",
        ),
        ForeignKeyConstraint(
            ("tenant_id",),
            ("tenants.id",),
            name="fk_admin_actions_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "actor_type IN "
            "('api_key', 'platform_admin', 'user', 'system', 'worker', 'migration')",
            name="ck_admin_actions_actor_type",
        ),
        CheckConstraint(
            "action IN ("
            "'approve_content', 'reject_content', 'retry_publication', "
            "'cancel_publication', 'resolve_publication_delivered', "
            "'resolve_publication_not_delivered', "
            "'resolve_publication_cancelled')",
            name="ck_admin_actions_action",
        ),
        CheckConstraint(
            "resource_type IN ('content', 'publication')",
            name="ck_admin_actions_resource_type",
        ),
        CheckConstraint(
            "expected_version >= 1 AND resulting_version > expected_version",
            name="ck_admin_actions_versions",
        ),
        Index(
            "ix_admin_actions_resource_created",
            "tenant_id",
            "resource_type",
            "resource_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
        Index(
            "ix_admin_actions_actor_created",
            "tenant_id",
            "actor_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
        Index(
            "ix_admin_actions_request_id",
            "tenant_id",
            "request_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_admin_actions_created",
            "tenant_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        nullable=False,
        default=LEGACY_TENANT_ID,
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    previous_state: Mapped[str] = mapped_column(String(64), nullable=False)
    resulting_state: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="api_key",
    )
    elevated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    expected_version: Mapped[int] = mapped_column(Integer, nullable=False)
    resulting_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    action_metadata: Mapped[dict[str, str]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
