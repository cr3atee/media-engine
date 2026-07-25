from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Offer(Base):
    """SQLAlchemy persistence model for parsed marketplace offers."""

    __tablename__ = "offers"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    marketplace: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    seller_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    seller_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    canonical_product_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
