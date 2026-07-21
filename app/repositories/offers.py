from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence

from app.parsers.models import ParsedOffer
from app.repositories.base import BaseRepository


class OfferRepository(BaseRepository):
    """Abstract storage contract for parsed marketplace offers."""

    @abstractmethod
    def save(self, offer: ParsedOffer) -> None:
        """Persist or update a parsed offer."""

    @abstractmethod
    def list_all(self) -> Sequence[ParsedOffer]:
        """Return all parsed offers."""
