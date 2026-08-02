from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from uuid import UUID

from app.domain.tenancy import LEGACY_TENANT_ID
from app.parsers.models import ParsedOffer
from app.repositories.base import BaseRepository, RepositoryIdentityConflictError


class OfferRepository(BaseRepository):
    """Abstract storage contract for parsed marketplace offers."""

    @abstractmethod
    async def save(self, offer: ParsedOffer) -> None:
        """Persist or update an offer, using its durable tenant ownership."""

    @abstractmethod
    async def get_by_identity(
        self,
        marketplace: str,
        external_id: str,
    ) -> ParsedOffer | None:
        """Return a legacy-tenant offer by marketplace and external ID."""

    @abstractmethod
    async def list_by_marketplace(
        self,
        marketplace: str,
    ) -> Sequence[ParsedOffer]:
        """Return legacy-tenant offers for one marketplace."""

    async def save_for_tenant(self, tenant_id: UUID, offer: ParsedOffer) -> None:
        """Persist an offer after validating its explicit tenant context."""
        _validate_tenant(tenant_id, offer.tenant_id)
        await self.save(offer)

    async def get_by_identity_for_tenant(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
    ) -> ParsedOffer | None:
        """Return an offer by tenant, marketplace, and external identifier."""
        if tenant_id == LEGACY_TENANT_ID:
            return await self.get_by_identity(marketplace, external_id)
        for offer in await self.list_by_tenant(tenant_id):
            if offer.marketplace == marketplace and offer.external_id == external_id:
                return offer
        return None

    async def list_by_marketplace_for_tenant(
        self,
        tenant_id: UUID,
        marketplace: str,
    ) -> Sequence[ParsedOffer]:
        """Return parsed offers for one tenant and marketplace."""
        if tenant_id == LEGACY_TENANT_ID:
            offers = await self.list_by_marketplace(marketplace)
            return tuple(offer for offer in offers if offer.tenant_id == tenant_id)
        return tuple(
            offer
            for offer in await self.list_by_tenant(tenant_id)
            if offer.marketplace == marketplace
        )

    async def list_by_tenant(self, tenant_id: UUID) -> Sequence[ParsedOffer]:
        """Return parsed offers owned by one tenant."""
        return tuple(
            offer for offer in await self.list_all() if offer.tenant_id == tenant_id
        )

    @abstractmethod
    async def list_all(self) -> Sequence[ParsedOffer]:
        """Return all parsed offers for explicit internal cross-tenant flows."""


def _validate_tenant(requested: UUID, actual: UUID) -> None:
    if requested != actual:
        msg = f"Offer tenant mismatch: requested {requested}, got {actual}."
        raise RepositoryIdentityConflictError(msg)
