from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class OfferSourceObservationRecord(Base):
    """Availability state observed by one marketplace integration."""

    __tablename__ = "offer_source_observations"
    __table_args__ = (
        CheckConstraint(
            "first_seen_at <= last_seen_at AND last_seen_at <= state_updated_at",
            name="ck_offer_source_observations_time_order",
        ),
        CheckConstraint(
            "(is_active AND unavailable_since IS NULL) OR "
            "(NOT is_active AND unavailable_since = state_updated_at)",
            name="ck_offer_source_observations_state",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "integration_id"),
            ("marketplace_integrations.tenant_id", "marketplace_integrations.id"),
            name="fk_offer_source_observations_integration",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "offer_id"),
            ("offers.tenant_id", "offers.id"),
            name="fk_offer_source_observations_offer",
            ondelete="CASCADE",
        ),
        Index(
            "ix_offer_source_observations_integration_state",
            "tenant_id",
            "integration_id",
            "is_active",
            "state_updated_at",
        ),
        Index(
            "ix_offer_source_observations_active_offer",
            "tenant_id",
            "offer_id",
            postgresql_where=text("is_active"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    integration_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    offer_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    state_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    unavailable_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
