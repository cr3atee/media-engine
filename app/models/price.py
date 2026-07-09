from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Price(Base):
    __tablename__ = "prices"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
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
