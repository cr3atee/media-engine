from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from uuid import UUID

from app.domain.tenancy import LEGACY_TENANT_ID
from app.parsers.models import ParsedOffer
from app.repositories.offers import OfferRepository


class MemoryOfferRepository(OfferRepository):
    """In-memory repository for parsed marketplace offers."""

    def __init__(self) -> None:
        """Initialize empty in-memory offer storage."""
        self._offers: list[ParsedOffer] = []

    async def save(self, offer: ParsedOffer) -> None:
        """Store or update an offer in deterministic tenant-local order."""
        tenant_id = offer.tenant_id
        if offer.external_id is not None:
            for index, stored_offer in enumerate(self._offers):
                if (
                    stored_offer.tenant_id == tenant_id
                    and stored_offer.marketplace == offer.marketplace
                    and stored_offer.external_id == offer.external_id
                ):
                    self._offers[index] = replace(
                        stored_offer,
                        title=_incoming_or_stored(offer.title, stored_offer.title),
                        url=_incoming_or_stored(offer.url, stored_offer.url),
                        price=_incoming_or_stored(offer.price, stored_offer.price),
                        currency=_incoming_or_stored(
                            offer.currency,
                            stored_offer.currency,
                        ),
                        seller_id=_incoming_or_stored(
                            offer.seller_id,
                            stored_offer.seller_id,
                        ),
                        seller_name=_incoming_or_stored(
                            offer.seller_name,
                            stored_offer.seller_name,
                        ),
                        canonical_product_id=_incoming_or_stored(
                            offer.canonical_product_id,
                            stored_offer.canonical_product_id,
                        ),
                    )
                    return

        self._offers.append(offer)

    async def get_by_identity(
        self,
        marketplace: str,
        external_id: str,
    ) -> ParsedOffer | None:
        """Return a legacy-tenant offer by stable marketplace identity."""
        return await self.get_by_identity_for_tenant(
            LEGACY_TENANT_ID,
            marketplace,
            external_id,
        )

    async def get_by_identity_for_tenant(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
    ) -> ParsedOffer | None:
        """Return an offer by tenant, marketplace, and external identifier."""
        for offer in self._offers:
            if (
                offer.tenant_id == tenant_id
                and offer.marketplace == marketplace
                and offer.external_id == external_id
            ):
                return offer
        return None

    async def list_by_marketplace(
        self,
        marketplace: str,
    ) -> Sequence[ParsedOffer]:
        """Return legacy-tenant offers for one marketplace."""
        return await self.list_by_marketplace_for_tenant(
            LEGACY_TENANT_ID,
            marketplace,
        )

    async def list_by_marketplace_for_tenant(
        self,
        tenant_id: UUID,
        marketplace: str,
    ) -> Sequence[ParsedOffer]:
        """Return offers for one tenant and marketplace."""
        return tuple(
            offer
            for offer in self._offers
            if offer.tenant_id == tenant_id and offer.marketplace == marketplace
        )

    async def list_by_tenant(self, tenant_id: UUID) -> Sequence[ParsedOffer]:
        """Return parsed offers for one tenant in insertion order."""
        return tuple(offer for offer in self._offers if offer.tenant_id == tenant_id)

    async def list_all(self) -> Sequence[ParsedOffer]:
        """Return all parsed offers in insertion order."""
        return tuple(self._offers)


def _incoming_or_stored[T](incoming: T | None, stored: T | None) -> T | None:
    return stored if incoming is None else incoming
