"""Platform-level role audit, deliberately not assigned to a fake tenant."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class ProductRoleActionRecord(Base):
    """Append-only accepted role command and stable replay result."""

    __tablename__ = "product_role_actions"
    __table_args__ = (
        CheckConstraint(
            "previous_role IN ('user', 'partner', 'moderator', 'admin') "
            "AND resulting_role IN ('user', 'partner', 'moderator', 'admin')",
            name="ck_product_role_actions_roles",
        ),
        CheckConstraint(
            "expected_version >= 1 AND resulting_version = expected_version + 1",
            name="ck_product_role_actions_versions",
        ),
        CheckConstraint(
            "length(btrim(reason)) > 0 AND length(btrim(idempotency_key)) > 0",
            name="ck_product_role_actions_nonempty",
        ),
        CheckConstraint(
            "(actor_user_id IS NULL AND actor_key = 'bootstrap') "
            "OR (actor_user_id IS NOT NULL "
            "AND actor_key = CAST(actor_user_id AS VARCHAR))",
            name="ck_product_role_actions_actor",
        ),
        Index(
            "uq_product_role_actions_replay",
            "actor_key",
            "idempotency_key",
            unique=True,
        ),
        Index("ix_product_role_actions_user_time", "user_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    actor_key: Mapped[str] = mapped_column(String(36), nullable=False)
    previous_role: Mapped[str] = mapped_column(String(16), nullable=False)
    resulting_role: Mapped[str] = mapped_column(String(16), nullable=False)
    expected_version: Mapped[int] = mapped_column(Integer, nullable=False)
    resulting_version: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
