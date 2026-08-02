from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.domain.tenancy import LEGACY_TENANT_ID


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        Index(
            "uq_products_tenant_marketplace_external_id",
            "tenant_id",
            "marketplace_id",
            "external_id",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", name="fk_products_tenant_id_tenants"),
        nullable=False,
        default=LEGACY_TENANT_ID,
    )
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
