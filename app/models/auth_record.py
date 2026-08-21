from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class UserCredentialRecord(Base):
    """SQLAlchemy persistence model for password verifier hashes."""

    __tablename__ = "user_credentials"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", name="pk_user_credentials"),
        ForeignKeyConstraint(
            ("user_id",),
            ("users.id",),
            name="fk_user_credentials_user",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "length(btrim(password_hash)) > 0",
            name="ck_user_credentials_password_hash_nonempty",
        ),
        CheckConstraint("version >= 1", name="ck_user_credentials_version"),
        CheckConstraint(
            "updated_at >= created_at",
            name="ck_user_credentials_timestamp_order",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class AuthSessionRecord(Base):
    """SQLAlchemy persistence model for refresh-token sessions."""

    __tablename__ = "auth_sessions"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_auth_sessions"),
        ForeignKeyConstraint(
            ("user_id",),
            ("users.id",),
            name="fk_auth_sessions_user",
            ondelete="RESTRICT",
        ),
        CheckConstraint("expires_at > created_at", name="ck_auth_sessions_expiry"),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_auth_sessions_revoked_at",
        ),
        CheckConstraint(
            "last_used_at IS NULL OR last_used_at >= created_at",
            name="ck_auth_sessions_last_used_at",
        ),
        CheckConstraint("version >= 1", name="ck_auth_sessions_version"),
        Index("uq_auth_sessions_refresh_token_hash", "refresh_token_hash", unique=True),
        Index("ix_auth_sessions_user_active", "user_id", "revoked_at", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    refresh_token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class PasswordResetTokenRecord(Base):
    """SQLAlchemy persistence model for one-use reset token hashes."""

    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_password_reset_tokens"),
        ForeignKeyConstraint(
            ("user_id",),
            ("users.id",),
            name="fk_password_reset_tokens_user",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="ck_password_reset_tokens_expiry",
        ),
        CheckConstraint(
            "used_at IS NULL OR used_at >= created_at",
            name="ck_password_reset_tokens_used_at",
        ),
        CheckConstraint("version >= 1", name="ck_password_reset_tokens_version"),
        Index("uq_password_reset_tokens_hash", "token_hash", unique=True),
        Index("ix_password_reset_tokens_user", "user_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
