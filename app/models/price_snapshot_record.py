from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.domain.tenancy import LEGACY_TENANT_ID


class PriceSnapshotRecord(Base):
    """SQLAlchemy persistence model for marketplace price snapshots."""

    __tablename__ = "price_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "tenant_id",
            name="uq_price_snapshots_id_tenant",
        ),
        UniqueConstraint(
            "tenant_id",
            "marketplace",
            "external_id",
            "collected_at",
            "price",
            "currency",
            name="uq_price_snapshots_exact_identity",
        ),
        Index(
            "ix_price_snapshots_history_order",
            "tenant_id",
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
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "tenants.id",
            name="fk_price_snapshots_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        nullable=False,
        default=LEGACY_TENANT_ID,
    )
    marketplace: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
