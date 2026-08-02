from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.domain.tenancy import LEGACY_TENANT_ID


class Price(Base):
    __tablename__ = "prices"
    __table_args__ = (
        ForeignKeyConstraint(
            ("product_id", "tenant_id"),
            ("products.id", "products.tenant_id"),
            name="fk_prices_product_tenant",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_prices_tenant_product_collected",
            "tenant_id",
            "product_id",
            "collected_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", name="fk_prices_tenant_id_tenants"),
        nullable=False,
        default=LEGACY_TENANT_ID,
    )
    product_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("products.id"),
        nullable=False,
    )
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    seller: Mapped[str] = mapped_column(String(255), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
