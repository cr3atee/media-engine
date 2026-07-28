from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence

from app.parsers.models import ParsedOffer
from app.repositories.base import BaseRepository


class OfferRepository(BaseRepository):
    """Abstract storage contract for parsed marketplace offers."""

    @abstractmethod
    async def save(self, offer: ParsedOffer) -> None:
        """Persist or update a parsed offer."""

    @abstractmethod
    async def get_by_identity(
        self,
        marketplace: str,
        external_id: str,
    ) -> ParsedOffer | None:
        """Return an offer by marketplace and external identifier."""

    @abstractmethod
    async def list_by_marketplace(self, marketplace: str) -> Sequence[ParsedOffer]:
        """Return parsed offers for one marketplace."""

    @abstractmethod
    async def list_all(self) -> Sequence[ParsedOffer]:
        """Return all parsed offers."""
