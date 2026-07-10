from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(slots=True, frozen=True)
class PriceChange:
    """Calculated price difference between two price snapshots."""

    previous_price: Decimal
    current_price: Decimal
    difference: Decimal
    percentage: Decimal
    is_price_drop: bool
