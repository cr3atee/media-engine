from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.domain.tenancy import LEGACY_TENANT_ID


class Offer(Base):
    """SQLAlchemy persistence model for parsed marketplace offers."""

    __tablename__ = "offers"
    __table_args__ = (
        Index(
            "uq_offers_marketplace_external_id_not_null",
            "tenant_id",
            "marketplace",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
        Index("ix_offers_tenant_created", "tenant_id", "created_at", "id"),
        Index("ix_offers_canonical_product_id", "canonical_product_id"),
        Index(
            "ix_offers_tenant_canonical_product",
            "tenant_id",
            "canonical_product_id",
            postgresql_where=text("canonical_product_id IS NOT NULL"),
        ),
        Index(
            "ix_offers_tenant_manual_active_created",
            "tenant_id",
            "created_at",
            "id",
            postgresql_where=text("manual_availability_status = 'active'"),
        ),
        Index(
            "ix_offers_tenant_marketplace_source_category",
            "tenant_id",
            "marketplace",
            "source_category_id",
            postgresql_where=text("source_category_id IS NOT NULL"),
        ),
        CheckConstraint(
            "manual_availability_status IN ('active', 'retired')",
            name="ck_offers_manual_availability_status",
        ),
        CheckConstraint(
            "manual_availability_version >= 1",
            name="ck_offers_manual_availability_version",
        ),
        CheckConstraint(
            "(manual_availability_status = 'active' "
            "AND manually_retired_at IS NULL) OR "
            "(manual_availability_status = 'retired' "
            "AND manually_retired_at IS NOT NULL)",
            name="ck_offers_manual_availability_state",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "canonical_product_id"),
            ("canonical_products.tenant_id", "canonical_products.id"),
            name="fk_offers_tenant_canonical_product",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_offers_tenant_id_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "tenants.id",
            name="fk_offers_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        nullable=False,
        default=LEGACY_TENANT_ID,
    )
    marketplace: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    seller_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    seller_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_category_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    source_category_name: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    canonical_product_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "canonical_products.id",
            name="fk_offers_canonical_product_id_canonical_products",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    manual_availability_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="active",
        server_default=text("'active'"),
    )
    manual_availability_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    manual_availability_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    manually_retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
