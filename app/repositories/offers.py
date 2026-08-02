from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from uuid import UUID

from app.parsers.models import ParsedOffer
from app.repositories.base import BaseRepository


class OfferRepository(BaseRepository):
    """Abstract storage contract for parsed marketplace offers."""

    @abstractmethod
    async def save(self, tenant_id: UUID, offer: ParsedOffer) -> None:
        """Persist or update a parsed offer for one explicit tenant."""

    @abstractmethod
    async def get_by_identity(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
    ) -> ParsedOffer | None:
        """Return an offer by tenant, marketplace, and external identifier."""

    @abstractmethod
    async def list_by_marketplace(
        self,
        tenant_id: UUID,
        marketplace: str,
    ) -> Sequence[ParsedOffer]:
        """Return parsed offers for one tenant and marketplace."""

    @abstractmethod
    async def list_by_tenant(self, tenant_id: UUID) -> Sequence[ParsedOffer]:
        """Return parsed offers owned by one tenant."""

    @abstractmethod
    async def list_all(self) -> Sequence[ParsedOffer]:
        """Return all parsed offers for explicit internal cross-tenant flows."""
