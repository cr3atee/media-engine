from __future__ import annotations

from collections.abc import Sequence

from app.parsers.models import ParsedOffer
from app.repositories.offers import OfferRepository


class MemoryOfferRepository(OfferRepository):
    """In-memory repository for parsed marketplace offers."""

    def __init__(self) -> None:
        """Initialize empty in-memory offer storage."""
        self._offers: list[ParsedOffer] = []

    def save(self, offer: ParsedOffer) -> None:
        """Store a parsed offer in insertion order."""
        self._offers.append(offer)

    def list_all(self) -> Sequence[ParsedOffer]:
        """Return all parsed offers in insertion order."""
        return tuple(self._offers)
