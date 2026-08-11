from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from uuid import UUID

from app.domain.tenancy import LEGACY_TENANT_ID
from app.parsers.models import ParsedOffer
from app.repositories.base import BaseRepository


class OfferRepository(BaseRepository):
    """Abstract storage contract for parsed marketplace offers."""

    @abstractmethod
    async def save(
        self,
        tenant_id: UUID | ParsedOffer,
        offer: ParsedOffer | None = None,
    ) -> None:
        """Persist or update a parsed offer for one explicit tenant."""

    @abstractmethod
    async def get_by_identity(
        self,
        tenant_id: UUID | str,
        marketplace: str,
        external_id: str | None = None,
    ) -> ParsedOffer | None:
        """Return an offer by tenant, marketplace, and external identifier."""

    @abstractmethod
    async def list_by_marketplace(
        self,
        tenant_id: UUID | str,
        marketplace: str | None = None,
    ) -> Sequence[ParsedOffer]:
        """Return parsed offers for one tenant and marketplace."""

    async def list_by_tenant(self, tenant_id: UUID) -> Sequence[ParsedOffer]:
        """Return parsed offers owned by one tenant."""
        return tuple(
            offer for offer in await self.list_all() if offer.tenant_id == tenant_id
        )

    @abstractmethod
    async def list_all(self) -> Sequence[ParsedOffer]:
        """Return all parsed offers for explicit internal cross-tenant flows."""


def resolve_offer_save_args(
    tenant_id_or_offer: UUID | ParsedOffer,
    offer: ParsedOffer | None,
) -> tuple[UUID, ParsedOffer]:
    """Resolve explicit tenant-aware and legacy offer-save call styles."""
    if isinstance(tenant_id_or_offer, ParsedOffer):
        if offer is not None:
            msg = "Offer must not be passed twice."
            raise TypeError(msg)
        return tenant_id_or_offer.tenant_id, tenant_id_or_offer
    if offer is None:
        msg = "Offer is required when tenant_id is passed explicitly."
        raise TypeError(msg)
    return tenant_id_or_offer, offer


def resolve_offer_identity_args(
    tenant_id_or_marketplace: UUID | str,
    marketplace_or_external_id: str,
    external_id: str | None,
) -> tuple[UUID, str, str]:
    """Resolve explicit tenant-aware and legacy offer-lookup call styles."""
    if isinstance(tenant_id_or_marketplace, UUID):
        if external_id is None:
            msg = "External ID is required when tenant_id is passed explicitly."
            raise TypeError(msg)
        return tenant_id_or_marketplace, marketplace_or_external_id, external_id
    if external_id is not None:
        msg = "Legacy offer lookup accepts only marketplace and external_id."
        raise TypeError(msg)
    return LEGACY_TENANT_ID, tenant_id_or_marketplace, marketplace_or_external_id


def resolve_offer_marketplace_args(
    tenant_id_or_marketplace: UUID | str,
    marketplace: str | None,
) -> tuple[UUID, str]:
    """Resolve explicit tenant-aware and legacy marketplace-list call styles."""
    if isinstance(tenant_id_or_marketplace, UUID):
        if marketplace is None:
            msg = "Marketplace is required when tenant_id is passed explicitly."
            raise TypeError(msg)
        return tenant_id_or_marketplace, marketplace
    if marketplace is not None:
        msg = "Legacy marketplace listing accepts only marketplace."
        raise TypeError(msg)
    return LEGACY_TENANT_ID, tenant_id_or_marketplace
