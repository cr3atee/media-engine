from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class UserRecord(Base):
    """SQLAlchemy persistence model for durable user identities."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("length(btrim(email)) > 0", name="ck_users_email_nonempty"),
        CheckConstraint("version >= 1", name="ck_users_version"),
        CheckConstraint(
            "updated_at >= created_at",
            name="ck_users_timestamp_order",
        ),
        Index("uq_users_email", "email", unique=True),
        Index("ix_users_enabled", "enabled"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
