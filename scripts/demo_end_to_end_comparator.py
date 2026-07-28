from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


async def main() -> None:
    """Demonstrate the full comparator flow using existing services only."""
    from app.comparator.difference import PriceDifferenceService
    from app.comparator.grouping import OfferGroupingService
    from app.comparator.models import MarketplaceOffer
    from app.comparator.result import ComparisonResultBuilder
    from app.comparator.selector import BestOfferSelector
    from app.models.canonical_product import CanonicalProduct
    from app.parsers.models import ParsedOffer
    from app.repositories.provider import create_memory_provider

    provider = create_memory_provider()

    canonical_id = uuid4()
    canonical_product = CanonicalProduct(
        id=canonical_id,
        name="Minecraft Premium",
        category=None,
        aliases=("minecraft",),
    )
    await provider.canonical_products.save(canonical_product)

    ggsel_offer = ParsedOffer(
        marketplace="ggsel",
        external_id="ggsel-1",
        title="Minecraft Premium",
        url="https://ggsel.net/item/1",
        price=Decimal("990"),
        currency="RUB",
        seller_id=None,
        seller_name="GGSEL Seller",
        canonical_product_id=None,
    )
    playerok_offer = ParsedOffer(
        marketplace="playerok",
        external_id="playerok-1",
        title="Minecraft Premium",
        url="https://playerok.com/item/1",
        price=Decimal("790"),
        currency="RUB",
        seller_id=None,
        seller_name="Playerok Seller",
        canonical_product_id=None,
    )

    await provider.offers.save(ggsel_offer)
    await provider.offers.save(playerok_offer)

    grouping_service = OfferGroupingService()
    selector = BestOfferSelector()
    difference_service = PriceDifferenceService()
    result_builder = ComparisonResultBuilder()
    stored_offers = await provider.offers.list_all()
    canonical_products = await provider.canonical_products.list_all()

    grouped = grouping_service.group(
        [MarketplaceOffer(offer=offer) for offer in stored_offers],
        canonical_products,
    )
    product_index = {product.id: product for product in canonical_products}

    for group in grouped:
        matched_product = (
            product_index.get(group.canonical_product_id)
            if group.canonical_product_id is not None
            else None
        )
        selection = selector.select(group)
        difference = difference_service.compare(selection)
        comparison_result = result_builder.build(
            matched_product,
            selection,
            difference,
        )

        print("Canonical Product")
        if comparison_result.canonical_product is None:
            print("  <unmatched>")
        else:
            print(f"  {comparison_result.canonical_product.name}")
        print()

        print("Marketplace Offers")
        for item in comparison_result.grouped_offers:
            offer = item.offer
            print(
                f"  - {offer.marketplace}: {offer.title} "
                f"{offer.price} {offer.currency}",
            )
        print()

        print("Selected Best Offer")
        if comparison_result.best_offer is None:
            print("  None")
        else:
            best = comparison_result.best_offer.offer
            print(f"  {best.marketplace}: {best.title} {best.price} {best.currency}")
        print()

        print("Price Differences")
        if not comparison_result.comparison_entries:
            print("  None")
        else:
            for entry in comparison_result.comparison_entries:
                offer = entry.offer.offer
                print(f"  - {offer.marketplace}: {offer.title}")
                print(f"    Absolute Difference: {entry.absolute_difference}")
                print(f"    Percentage Difference: {entry.percentage_difference}")
                if entry.reason is not None:
                    print(f"    Reason: {entry.reason}")
        print()

        print("Comparison Result")
        print(f"  Status: {comparison_result.status.value}")
        print(f"  Canonical Product ID: {comparison_result.canonical_product_id}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
