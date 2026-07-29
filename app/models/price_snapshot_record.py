from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class PriceSnapshotRecord(Base):
    """SQLAlchemy persistence model for marketplace price snapshots."""

    __tablename__ = "price_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "marketplace",
            "external_id",
            "collected_at",
            "price",
            "currency",
            name="uq_price_snapshots_exact_identity",
        ),
        Index(
            "ix_price_snapshots_history_order",
            "marketplace",
            "external_id",
            "collected_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    marketplace: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
