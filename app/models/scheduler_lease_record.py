from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, PrimaryKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class SchedulerLeaseRecord(Base):
    """SQLAlchemy persistence model for scheduler execution leases."""

    __tablename__ = "scheduler_leases"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(job_name)) > 0",
            name="ck_scheduler_leases_job_name_nonempty",
        ),
        CheckConstraint(
            "length(btrim(owner_id)) > 0",
            name="ck_scheduler_leases_owner_id_nonempty",
        ),
        CheckConstraint(
            "expires_at > acquired_at",
            name="ck_scheduler_leases_expiry_after_acquisition",
        ),
        PrimaryKeyConstraint("job_name", name="pk_scheduler_leases"),
        Index("ix_scheduler_leases_expires_at", "expires_at"),
    )

    job_name: Mapped[str] = mapped_column(String(255))
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
