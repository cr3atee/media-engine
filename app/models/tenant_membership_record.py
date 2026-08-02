from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class TenantMembershipRecord(Base):
    """SQLAlchemy persistence model for tenant membership and role grants."""

    __tablename__ = "tenant_memberships"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_tenant_memberships"),
        UniqueConstraint(
            "user_id",
            "tenant_id",
            name="uq_tenant_memberships_user_tenant",
        ),
        ForeignKeyConstraint(
            ("user_id",),
            ("users.id",),
            name="fk_tenant_memberships_user",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("tenant_id",),
            ("tenants.id",),
            name="fk_tenant_memberships_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "role IN ('owner', 'administrator', 'reviewer', 'operator', 'viewer')",
            name="ck_tenant_memberships_role",
        ),
        CheckConstraint("version >= 1", name="ck_tenant_memberships_version"),
        CheckConstraint(
            "updated_at >= joined_at",
            name="ck_tenant_memberships_timestamp_order",
        ),
        Index("ix_tenant_memberships_user", "user_id", "is_active"),
        Index("ix_tenant_memberships_tenant", "tenant_id", "is_active"),
        Index("ix_tenant_memberships_role", "tenant_id", "role"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
