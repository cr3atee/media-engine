"""Demonstrate explicit canonical links feeding the existing comparator."""

from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.comparator.difference import PriceDifferenceService  # noqa: E402
from app.comparator.grouping import OfferGroupingService  # noqa: E402
from app.comparator.models import MarketplaceOffer  # noqa: E402
from app.comparator.result import ComparisonResultBuilder  # noqa: E402
from app.comparator.selector import BestOfferSelector  # noqa: E402
from app.models.canonical_product import CanonicalProduct  # noqa: E402
from app.parsers.models import ParsedOffer  # noqa: E402
from app.repositories.provider import create_memory_provider  # noqa: E402
from app.services.canonical_offer_linking import (  # noqa: E402
    CanonicalOfferLinkService,
    LinkCanonicalOfferCommand,
)
from app.services.repository_scope import create_memory_repository_scope  # noqa: E402


async def main() -> None:
    """Link reviewed offers and print their unified comparison result."""
    tenant_id = uuid4()
    product = CanonicalProduct(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Minecraft: Java & Bedrock Edition for PC - Global Key",
        category="Games",
        aliases=("minecraft java bedrock pc global",),
    )
    offers = (
        _offer(
            tenant_id=tenant_id,
            marketplace="ggsel",
            external_id="ggsel-reviewed",
            title="Minecraft: Java & Bedrock Edition | PC | GLOBAL",
            price=Decimal("1999.00"),
        ),
        _offer(
            tenant_id=tenant_id,
            marketplace="funpay",
            external_id="funpay-reviewed",
            title="Minecraft: Java & Bedrock for PC, digital key",
            price=Decimal("1890.00"),
        ),
    )
    provider = create_memory_provider()
    await provider.canonical_products.save(product)
    for offer in offers:
        await provider.offers.save(tenant_id, offer)

    linking = CanonicalOfferLinkService(create_memory_repository_scope(provider))
    for offer in offers:
        await linking.link(
            LinkCanonicalOfferCommand(
                tenant_id=tenant_id,
                canonical_product_id=product.id,
                marketplace=offer.marketplace,
                external_id=offer.external_id or "",
            )
        )

    stored_offers = await provider.offers.list_by_tenant(tenant_id)
    groups = OfferGroupingService().group(
        [MarketplaceOffer(offer=offer) for offer in stored_offers],
        [product],
    )
    selection = BestOfferSelector().select(groups[0])
    differences = PriceDifferenceService().compare(selection)
    result = ComparisonResultBuilder().build(product, selection, differences)

    print(f"Canonical product: {product.name}")
    print(f"Linked offers: {len(result.grouped_offers)}")
    for item in result.grouped_offers:
        offer = item.offer
        print(f"- {offer.marketplace}: {offer.price} {offer.currency}")
    best = result.best_offer.offer if result.best_offer is not None else None
    print(
        "Best offer: "
        + (
            f"{best.marketplace} {best.price} {best.currency}"
            if best is not None
            else "unavailable"
        )
    )
    print(f"Comparison status: {result.status.value}")


def _offer(
    *,
    tenant_id: UUID,
    marketplace: str,
    external_id: str,
    title: str,
    price: Decimal,
) -> ParsedOffer:
    return ParsedOffer(
        tenant_id=tenant_id,
        marketplace=marketplace,
        external_id=external_id,
        title=title,
        url=f"https://example.com/{marketplace}/{external_id}",
        price=price,
        currency="RUB",
    )


if __name__ == "__main__":
    asyncio.run(main())
