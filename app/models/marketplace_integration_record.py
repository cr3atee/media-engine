from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.domain.marketplace_integrations import (
    MarketplaceAuthType,
    MarketplaceIntegrationStatus,
)


class MarketplaceIntegrationRecord(Base):
    """SQLAlchemy persistence model for tenant-owned marketplace integrations."""

    __tablename__ = "marketplace_integrations"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(marketplace)) > 0",
            name="ck_marketplace_integrations_marketplace_nonempty",
        ),
        CheckConstraint(
            "length(btrim(display_name)) > 0",
            name="ck_marketplace_integrations_display_name_nonempty",
        ),
        CheckConstraint(
            "external_account_id IS NULL OR length(btrim(external_account_id)) > 0",
            name="ck_marketplace_integrations_external_account_nonempty",
        ),
        CheckConstraint(
            "source_url IS NULL OR length(btrim(source_url)) > 0",
            name="ck_marketplace_integrations_source_url_nonempty",
        ),
        CheckConstraint(
            "last_error_code IS NULL OR length(btrim(last_error_code)) > 0",
            name="ck_marketplace_integrations_last_error_code_nonempty",
        ),
        CheckConstraint(
            "last_error_summary IS NULL OR length(btrim(last_error_summary)) > 0",
            name="ck_marketplace_integrations_last_error_summary_nonempty",
        ),
        CheckConstraint(
            "status IN ('draft', 'active', 'disabled', 'error')",
            name="ck_marketplace_integrations_status",
        ),
        CheckConstraint(
            "auth_type IN ('none', 'api_key', 'cookie', 'session')",
            name="ck_marketplace_integrations_auth_type",
        ),
        CheckConstraint(
            "credential_reference IS NULL OR length(btrim(credential_reference)) > 0",
            name="ck_marketplace_integrations_credential_reference_nonempty",
        ),
        CheckConstraint(
            "credential_version >= 0",
            name="ck_marketplace_integrations_credential_version",
        ),
        CheckConstraint(
            "auth_type <> 'none' OR credential_reference IS NULL",
            name="ck_marketplace_integrations_auth_none_without_reference",
        ),
        CheckConstraint(
            "("
            "credential_reference IS NULL "
            "AND credential_configured_at IS NULL "
            "AND credential_last_rotated_at IS NULL "
            "AND credential_version = 0"
            ") OR ("
            "credential_reference IS NOT NULL "
            "AND credential_configured_at IS NOT NULL "
            "AND credential_version >= 1"
            ")",
            name="ck_marketplace_integrations_credential_state",
        ),
        CheckConstraint(
            "credential_last_rotated_at IS NULL "
            "OR credential_last_rotated_at >= credential_configured_at",
            name="ck_marketplace_integrations_credential_rotation_time",
        ),
        CheckConstraint("version >= 1", name="ck_marketplace_integrations_version"),
        CheckConstraint(
            "updated_at >= created_at",
            name="ck_marketplace_integrations_timestamp_order",
        ),
        CheckConstraint(
            "last_successful_run_at IS NULL OR last_successful_run_at >= created_at",
            name="ck_marketplace_integrations_success_time",
        ),
        CheckConstraint(
            "last_failed_run_at IS NULL OR last_failed_run_at >= created_at",
            name="ck_marketplace_integrations_failure_time",
        ),
        Index(
            "uq_marketplace_integrations_tenant_marketplace_external_account",
            "tenant_id",
            "marketplace",
            "external_account_id",
            unique=True,
            postgresql_where=text("external_account_id IS NOT NULL"),
        ),
        Index(
            "uq_marketplace_integrations_tenant_marketplace_source_url",
            "tenant_id",
            "marketplace",
            "source_url",
            unique=True,
            postgresql_where=text("source_url IS NOT NULL"),
        ),
        Index("ix_marketplace_integrations_tenant", "tenant_id", "marketplace", "id"),
        Index(
            "ix_marketplace_integrations_enabled_runs",
            "enabled",
            "status",
            "created_at",
            "id",
        ),
        Index(
            "ix_marketplace_integrations_credentials",
            "tenant_id",
            "auth_type",
            "credential_configured_at",
            postgresql_where=text("credential_reference IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "tenants.id",
            name="fk_marketplace_integrations_tenant",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    marketplace: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=MarketplaceIntegrationStatus.DRAFT.value,
    )
    external_account_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    auth_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=MarketplaceAuthType.NONE.value,
    )
    credential_reference: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )
    credential_configured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    credential_last_rotated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    credential_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    last_successful_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_failed_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error_summary: Mapped[str | None] = mapped_column(
        String(2000),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
