from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from uuid import UUID

from app.parsers.models import ParsedOffer
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.offers import (
    OfferRepository,
    resolve_offer_identity_args,
    resolve_offer_marketplace_args,
    resolve_offer_save_args,
)


class MemoryOfferRepository(OfferRepository):
    """In-memory repository for parsed marketplace offers."""

    def __init__(self) -> None:
        """Initialize empty in-memory offer storage."""
        self._offers: list[ParsedOffer] = []

    async def save(
        self,
        tenant_id: UUID | ParsedOffer,
        offer: ParsedOffer | None = None,
    ) -> None:
        """Store or update a parsed offer in deterministic order."""
        tenant_id, offer = resolve_offer_save_args(tenant_id, offer)
        _validate_tenant(tenant_id, offer.tenant_id)
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
        tenant_id: UUID | str,
        marketplace: str,
        external_id: str | None = None,
    ) -> ParsedOffer | None:
        """Return an offer by marketplace and external identifier."""
        tenant_id, marketplace, external_id = resolve_offer_identity_args(
            tenant_id,
            marketplace,
            external_id,
        )
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
        tenant_id: UUID | str,
        marketplace: str | None = None,
    ) -> Sequence[ParsedOffer]:
        """Return parsed offers for one marketplace in insertion order."""
        tenant_id, marketplace = resolve_offer_marketplace_args(
            tenant_id,
            marketplace,
        )
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


def _validate_tenant(requested: UUID, actual: UUID) -> None:
    if requested != actual:
        msg = f"Offer tenant mismatch: requested {requested}, got {actual}."
        raise RepositoryIdentityConflictError(msg)
