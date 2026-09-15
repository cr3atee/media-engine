from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import UUID

from app.parsers.models import ParsedOffer
from app.services.repository_scope import RepositoryScopeFactory


@dataclass(slots=True, frozen=True, kw_only=True)
class LinkCanonicalOfferCommand:
    """Explicit tenant-scoped instruction to link one offer to one product."""

    tenant_id: UUID
    canonical_product_id: UUID
    marketplace: str
    external_id: str


class CanonicalOfferLinkError(Exception):
    """Base failure for safe explicit canonical-offer linking."""


class CanonicalProductUnavailableError(CanonicalOfferLinkError):
    """Raised when the target product is unavailable inside the tenant."""


class MarketplaceOfferUnavailableError(CanonicalOfferLinkError):
    """Raised when the target marketplace offer is unavailable inside the tenant."""


class CanonicalOfferLinkConflictError(CanonicalOfferLinkError):
    """Raised when an offer is already linked to another canonical product."""


class CanonicalOfferLinkService:
    """Persist explicit reviewed offer links without performing title matching."""

    def __init__(self, repository_scope_factory: RepositoryScopeFactory) -> None:
        """Initialize the service with transaction-scoped repositories."""
        self._repository_scope_factory = repository_scope_factory

    async def link(self, command: LinkCanonicalOfferCommand) -> ParsedOffer:
        """Idempotently link an existing offer to a tenant-owned product."""
        async with self._repository_scope_factory() as repositories:
            product = await repositories.canonical_products.get_by_tenant_and_id(
                command.tenant_id,
                command.canonical_product_id,
            )
            if product is None:
                raise CanonicalProductUnavailableError(
                    "Canonical product is unavailable for this tenant."
                )

            offer = await repositories.offers.get_by_identity(
                command.tenant_id,
                command.marketplace,
                command.external_id,
            )
            if offer is None:
                raise MarketplaceOfferUnavailableError(
                    "Marketplace offer is unavailable for this tenant."
                )

            if offer.canonical_product_id == command.canonical_product_id:
                return offer
            if offer.canonical_product_id is not None:
                raise CanonicalOfferLinkConflictError(
                    "Marketplace offer is already linked to another product."
                )

            linked_offer = replace(
                offer,
                canonical_product_id=command.canonical_product_id,
            )
            await repositories.offers.save(command.tenant_id, linked_offer)
            return linked_offer
