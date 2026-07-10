from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(slots=True, frozen=True)
class PriceSnapshot:
    """Database-independent price snapshot collected from a marketplace."""

    marketplace: str
    external_id: str
    price: Decimal
    currency: str
    collected_at: datetime
