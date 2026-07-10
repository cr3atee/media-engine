from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(slots=True, kw_only=True)
class ParsedOffer:
    """Raw marketplace offer extracted by a source parser."""

    marketplace: str
    external_id: str
    title: str
    url: str
    price: Decimal
    currency: str
    seller_id: str | None = None
    seller_name: str | None = None
