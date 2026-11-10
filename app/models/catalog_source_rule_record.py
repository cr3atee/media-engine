from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class CatalogSourceRuleRecord(Base):
    """SQLAlchemy persistence model for verified source-category rules."""

    __tablename__ = "catalog_source_rules"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(marketplace)) > 0",
            name="ck_catalog_source_rules_marketplace_nonempty",
        ),
        CheckConstraint(
            "length(btrim(source_category_id)) > 0",
            name="ck_catalog_source_rules_source_id_nonempty",
        ),
        CheckConstraint(
            "source_category_name IS NULL OR length(btrim(source_category_name)) > 0",
            name="ck_catalog_source_rules_source_name_nonempty",
        ),
        CheckConstraint(
            "length(btrim(hub_code)) > 0",
            name="ck_catalog_source_rules_hub_code_nonempty",
        ),
        CheckConstraint(
            "length(btrim(section_code)) > 0",
            name="ck_catalog_source_rules_section_code_nonempty",
        ),
        CheckConstraint(
            "updated_at >= created_at",
            name="ck_catalog_source_rules_timestamp_order",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_catalog_source_rules_version",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "integration_id"),
            ("marketplace_integrations.tenant_id", "marketplace_integrations.id"),
            name="fk_catalog_source_rules_integration",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "integration_id",
            "marketplace",
            "source_category_id",
            name="uq_catalog_source_rules_source_identity",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_catalog_source_rules_tenant_id_id",
        ),
        Index(
            "ix_catalog_source_rules_tenant_hub_section",
            "tenant_id",
            "hub_code",
            "section_code",
        ),
        Index(
            "ix_catalog_source_rules_tenant_integration",
            "tenant_id",
            "integration_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    integration_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    marketplace: Mapped[str] = mapped_column(String(64), nullable=False)
    source_category_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_category_name: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    hub_code: Mapped[str] = mapped_column(String(64), nullable=False)
    section_code: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
