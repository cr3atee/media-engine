from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, computed_field


class BaseEvent(BaseModel):
    """Base domain event model."""

    event_type: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PriceDropEvent(BaseEvent):
    """Domain event describing a product price drop."""

    event_type: str = "price_drop"
    title: str
    marketplace: str
    old_price: float
    new_price: float
    currency: str = "RUB"

    if TYPE_CHECKING:

        @property
        def discount_percent(self) -> float:
            """Return the percentage decrease from the old price to the new price."""
            return self._discount_percent()

    else:

        @computed_field
        @property
        def discount_percent(self) -> float:
            """Return the percentage decrease from the old price to the new price."""
            return self._discount_percent()

    def _discount_percent(self) -> float:
        if self.old_price == 0:
            return 0.0
        return ((self.old_price - self.new_price) / self.old_price) * 100
