from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.comparator.grouping import OfferGroupingService
from app.comparator.models import MarketplaceOffer
from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer
from app.repositories.provider import create_memory_provider
from app.services.canonical_offer_linking import (
    CanonicalOfferLinkConflictError,
    CanonicalOfferLinkService,
    CanonicalProductUnavailableError,
    LinkCanonicalOfferCommand,
    MarketplaceOfferUnavailableError,
)
from app.services.repository_scope import create_memory_repository_scope


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run one async service scenario without an async pytest plugin."""
    return asyncio.run(awaitable)


def test_explicit_link_is_idempotent_and_drives_grouping() -> None:
    """A reviewed link bypasses title guessing and survives repository reads."""

    async def scenario() -> None:
        tenant_id = uuid4()
        product = _product(tenant_id=tenant_id)
        offer = _offer(tenant_id=tenant_id, title="Source title with noisy words")
        provider = create_memory_provider()
        await provider.canonical_products.save(product)
        await provider.offers.save(tenant_id, offer)
        service = CanonicalOfferLinkService(create_memory_repository_scope(provider))
        command = LinkCanonicalOfferCommand(
            tenant_id=tenant_id,
            canonical_product_id=product.id,
            marketplace=offer.marketplace,
            external_id=offer.external_id or "",
        )

        linked = await service.link(command)
        repeated = await service.link(command)
        stored = await provider.offers.get_by_identity(
            tenant_id,
            offer.marketplace,
            offer.external_id,
        )
        groups = OfferGroupingService().group(
            [MarketplaceOffer(offer=linked)],
            [product],
        )

        assert linked.canonical_product_id == product.id
        assert repeated == linked
        assert stored == linked
        assert len(groups) == 1
        assert groups[0].canonical_product_id == product.id

    run_async(scenario())


def test_link_rejects_cross_tenant_product_without_mutation() -> None:
    """A tenant cannot attach its offer to another tenant's product."""

    async def scenario() -> None:
        owner_tenant_id = uuid4()
        offer_tenant_id = uuid4()
        product = _product(tenant_id=owner_tenant_id)
        offer = _offer(tenant_id=offer_tenant_id)
        provider = create_memory_provider()
        await provider.canonical_products.save(product)
        await provider.offers.save(offer_tenant_id, offer)
        service = CanonicalOfferLinkService(create_memory_repository_scope(provider))

        with pytest.raises(CanonicalProductUnavailableError):
            await service.link(
                LinkCanonicalOfferCommand(
                    tenant_id=offer_tenant_id,
                    canonical_product_id=product.id,
                    marketplace=offer.marketplace,
                    external_id=offer.external_id or "",
                )
            )

        stored = await provider.offers.get_by_identity(
            offer_tenant_id,
            offer.marketplace,
            offer.external_id,
        )
        assert stored == offer

    run_async(scenario())


def test_link_rejects_reassignment_to_another_product() -> None:
    """An existing reviewed link cannot be silently overwritten."""

    async def scenario() -> None:
        tenant_id = uuid4()
        first_product = _product(tenant_id=tenant_id)
        second_product = _product(tenant_id=tenant_id)
        offer = _offer(
            tenant_id=tenant_id,
            canonical_product_id=first_product.id,
        )
        provider = create_memory_provider()
        await provider.canonical_products.save(first_product)
        await provider.canonical_products.save(second_product)
        await provider.offers.save(tenant_id, offer)
        service = CanonicalOfferLinkService(create_memory_repository_scope(provider))

        with pytest.raises(CanonicalOfferLinkConflictError):
            await service.link(
                LinkCanonicalOfferCommand(
                    tenant_id=tenant_id,
                    canonical_product_id=second_product.id,
                    marketplace=offer.marketplace,
                    external_id=offer.external_id or "",
                )
            )

        stored = await provider.offers.get_by_identity(
            tenant_id,
            offer.marketplace,
            offer.external_id,
        )
        assert stored == offer

    run_async(scenario())


@pytest.mark.parametrize("missing", ["product", "offer"])
def test_link_reports_missing_records(missing: str) -> None:
    """Missing curated inputs fail explicitly instead of creating records."""

    async def scenario() -> None:
        tenant_id = uuid4()
        product = _product(tenant_id=tenant_id)
        offer = _offer(tenant_id=tenant_id)
        provider = create_memory_provider()
        if missing != "product":
            await provider.canonical_products.save(product)
        if missing != "offer":
            await provider.offers.save(tenant_id, offer)
        service = CanonicalOfferLinkService(create_memory_repository_scope(provider))
        expected_error = (
            CanonicalProductUnavailableError
            if missing == "product"
            else MarketplaceOfferUnavailableError
        )

        with pytest.raises(expected_error):
            await service.link(
                LinkCanonicalOfferCommand(
                    tenant_id=tenant_id,
                    canonical_product_id=product.id,
                    marketplace=offer.marketplace,
                    external_id=offer.external_id or "",
                )
            )

    run_async(scenario())


def test_grouping_does_not_match_across_tenants() -> None:
    """Automatic title matching considers only same-tenant products."""
    offer = _offer(tenant_id=uuid4(), title="Minecraft Java Bedrock")
    foreign_product = _product(
        tenant_id=uuid4(),
        name="Minecraft Java Bedrock",
    )

    groups = OfferGroupingService().group(
        [MarketplaceOffer(offer=offer)],
        [foreign_product],
    )

    assert len(groups) == 1
    assert groups[0].canonical_product_id is None


def test_unlinked_offer_keeps_same_tenant_automatic_matching() -> None:
    """Unlinked offers retain the existing deterministic matching fallback."""
    tenant_id = uuid4()
    offer = _offer(tenant_id=tenant_id, title="Minecraft Java Bedrock")
    product = _product(
        tenant_id=tenant_id,
        name="Minecraft Java Bedrock",
    )

    groups = OfferGroupingService().group(
        [MarketplaceOffer(offer=offer)],
        [product],
    )

    assert len(groups) == 1
    assert groups[0].canonical_product_id == product.id


def test_unknown_explicit_link_does_not_fall_back_to_title_matching() -> None:
    """An unresolved persisted link fails closed instead of being re-guessed."""
    tenant_id = uuid4()
    offer = _offer(
        tenant_id=tenant_id,
        title="Minecraft Java Bedrock",
        canonical_product_id=uuid4(),
    )
    candidate = _product(
        tenant_id=tenant_id,
        name="Minecraft Java Bedrock",
    )

    groups = OfferGroupingService().group(
        [MarketplaceOffer(offer=offer)],
        [candidate],
    )

    assert len(groups) == 1
    assert groups[0].canonical_product_id is None


def _product(
    *,
    tenant_id: UUID,
    name: str = "Minecraft: Java & Bedrock Edition for PC - Global Key",
) -> CanonicalProduct:
    return CanonicalProduct(
        id=uuid4(),
        tenant_id=tenant_id,
        name=name,
        category="Games",
        aliases=("minecraft java bedrock pc global",),
    )


def _offer(
    *,
    tenant_id: UUID,
    title: str = "Minecraft Java and Bedrock PC Key",
    canonical_product_id: UUID | None = None,
) -> ParsedOffer:
    return ParsedOffer(
        tenant_id=tenant_id,
        marketplace="ggsel",
        external_id="offer-1",
        title=title,
        url="https://ggsel.net/en/catalog/product/example",
        price=Decimal("1999.00"),
        currency="RUB",
        canonical_product_id=canonical_product_id,
    )
