from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.identity import normalize_utc


class OfferAvailabilityStatus(StrEnum):
    """Explicit operator-controlled availability state for one offer."""

    ACTIVE = "active"
    RETIRED = "retired"


@dataclass(slots=True, frozen=True, kw_only=True)
class OfferAvailabilityState:
    """Versioned manual availability state independent of source observations."""

    offer_id: UUID
    tenant_id: UUID
    marketplace: str
    external_id: str
    status: OfferAvailabilityStatus
    version: int
    updated_at: datetime
    retired_at: datetime | None = None

    def __post_init__(self) -> None:
        marketplace = self.marketplace.strip().lower()
        external_id = self.external_id.strip()
        status = OfferAvailabilityStatus(self.status)
        updated_at = normalize_utc(self.updated_at, field_name="updated_at")
        retired_at = (
            normalize_utc(self.retired_at, field_name="retired_at")
            if self.retired_at is not None
            else None
        )
        if not marketplace:
            raise ValueError("Offer marketplace must not be empty.")
        if not external_id:
            raise ValueError("Offer external ID must not be empty.")
        if self.version < 1:
            raise ValueError("Offer availability version must be positive.")
        if status is OfferAvailabilityStatus.ACTIVE and retired_at is not None:
            raise ValueError("Active offer availability cannot have a retirement time.")
        if status is OfferAvailabilityStatus.RETIRED and retired_at is None:
            raise ValueError("Retired offer availability requires a retirement time.")
        object.__setattr__(self, "marketplace", marketplace)
        object.__setattr__(self, "external_id", external_id)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "updated_at", updated_at)
        object.__setattr__(self, "retired_at", retired_at)
