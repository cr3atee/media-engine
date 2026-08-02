from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class TenantRecord(Base):
    """SQLAlchemy persistence model for tenant/workspace identities."""

    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="ck_tenants_name_nonempty"),
        CheckConstraint("length(btrim(slug)) > 0", name="ck_tenants_slug_nonempty"),
        CheckConstraint("version >= 1", name="ck_tenants_version"),
        CheckConstraint(
            "updated_at >= created_at",
            name="ck_tenants_timestamp_order",
        ),
        Index("uq_tenants_slug", "slug", unique=True),
        Index("ix_tenants_active", "is_active"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
