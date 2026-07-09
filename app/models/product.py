from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    marketplace_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("marketplaces.id"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
