from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class CanonicalOfferDecisionRecord(Base):
    """Immutable SQLAlchemy record for one reviewed offer/product pair."""

    __tablename__ = "canonical_offer_decisions"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_canonical_offer_decisions"),
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_canonical_offer_decisions_idempotency",
        ),
        UniqueConstraint(
            "tenant_id",
            "marketplace",
            "external_id",
            "canonical_product_id",
            name="uq_canonical_offer_decisions_pair",
        ),
        ForeignKeyConstraint(
            ("tenant_id",),
            ("tenants.id",),
            name="fk_canonical_offer_decisions_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "canonical_product_id"),
            ("canonical_products.tenant_id", "canonical_products.id"),
            name="fk_canonical_offer_decisions_product",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "decision IN ('confirmed', 'rejected')",
            name="ck_canonical_offer_decisions_decision",
        ),
        CheckConstraint(
            "actor_type IN "
            "('api_key', 'platform_admin', 'user', 'system', 'worker', 'migration')",
            name="ck_canonical_offer_decisions_actor_type",
        ),
        CheckConstraint(
            "length(btrim(marketplace)) > 0 "
            "AND length(btrim(external_id)) > 0 "
            "AND length(btrim(actor_id)) > 0 "
            "AND length(btrim(request_id)) > 0 "
            "AND length(btrim(idempotency_key)) > 0",
            name="ck_canonical_offer_decisions_nonempty",
        ),
        CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_canonical_offer_decisions_fingerprint",
        ),
        Index(
            "ix_canonical_offer_decisions_offer_created",
            "tenant_id",
            "marketplace",
            "external_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    marketplace: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_product_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
