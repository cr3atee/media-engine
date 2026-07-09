from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from uuid import UUID, uuid4


class EventType(str, Enum):
    PRICE_CHANGED = "price_changed"
    NEW_PRODUCT = "new_product"
    ARBITRAGE_FOUND = "arbitrage_found"
    COMMISSION_CHANGED = "commission_changed"
    POPULARITY_CHANGED = "popularity_changed"


@dataclass(slots=True, frozen=True)
class Event:
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    source: str = ""


@dataclass(slots=True, frozen=True)
class PriceChangedEvent(Event):
    pass


@dataclass(slots=True, frozen=True)
class NewProductEvent(Event):
    pass


@dataclass(slots=True, frozen=True)
class ArbitrageFoundEvent(Event):
    pass


@dataclass(slots=True, frozen=True)
class CommissionChangedEvent(Event):
    pass


@dataclass(slots=True, frozen=True)
class PopularityChangedEvent(Event):
    pass
