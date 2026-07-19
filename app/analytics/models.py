from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(slots=True, frozen=True)
class PriceChange:
    """Calculated price difference between two price snapshots."""

    previous_price: Decimal
    current_price: Decimal
    difference: Decimal
    percentage: Decimal
    is_price_drop: bool
    marketplace: str | None = None
    product_identifier: str | None = None
    timestamp: datetime | None = None

    @property
    def old_price(self) -> Decimal:
        """Return the previous snapshot price."""
        return self.previous_price

    @property
    def new_price(self) -> Decimal:
        """Return the current snapshot price."""
        return self.current_price

    @property
    def absolute_difference(self) -> Decimal:
        """Return the absolute price difference."""
        return abs(self.difference)

    @property
    def percentage_difference(self) -> Decimal:
        """Return the signed percentage difference."""
        return self.percentage
