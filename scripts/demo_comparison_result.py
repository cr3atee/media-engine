from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

from decimal import Decimal

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    """Build and print a full comparison result for one canonical product."""
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
    provider.canonical_products.save(canonical_product)

    offers = [
        ParsedOffer(
            marketplace="ggsel",
            external_id="ggsel-1",
            title="Minecraft Premium",
            url="https://ggsel.net/item/1",
            price=Decimal("990"),
            currency="RUB",
            seller_id=None,
            seller_name="Seller One",
            canonical_product_id=canonical_id,
        ),
        ParsedOffer(
            marketplace="playerok",
            external_id="playerok-1",
            title="Minecraft Premium",
            url="https://playerok.com/item/1",
            price=Decimal("790"),
            currency="RUB",
            seller_id=None,
            seller_name="Seller Two",
            canonical_product_id=canonical_id,
        ),
        ParsedOffer(
            marketplace="funpay",
            external_id="funpay-1",
            title="Minecraft Premium",
            url="https://funpay.com/item/1",
            price=None,
            currency="RUB",
            seller_id=None,
            seller_name="Seller Three",
            canonical_product_id=canonical_id,
        ),
    ]
    for offer in offers:
        provider.offers.save(offer)

    grouping_service = OfferGroupingService()
    selector = BestOfferSelector()
    difference_service = PriceDifferenceService()
    result_builder = ComparisonResultBuilder()

    grouped = grouping_service.group(
        [MarketplaceOffer(offer=offer) for offer in provider.offers.list_all()],
        provider.canonical_products.list_all(),
    )

    canonical_index = {
        product.id: product for product in provider.canonical_products.list_all()
    }

    for group in grouped:
        selection = selector.select(group)
        difference = difference_service.compare(selection)
        comparison_result = result_builder.build(
            canonical_index.get(group.canonical_product_id)
            if group.canonical_product_id is not None
            else None,
            selection,
            difference,
        )

        print("Canonical Product")
        if comparison_result.canonical_product is None:
            print("  <unmatched>")
        else:
            print(f"  {comparison_result.canonical_product.name}")

        print("Best Offer")
        if comparison_result.best_offer is None:
            print("  None")
        else:
            best = comparison_result.best_offer.offer
            print(f"  {best.marketplace}: {best.title} {best.price} {best.currency}")

        print("All Marketplace Offers")
        for item in comparison_result.grouped_offers:
            offer = item.offer
            print(f"  - {offer.marketplace}: {offer.title} {offer.price} {offer.currency}")

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

        print(f"Comparison Status: {comparison_result.status.value}")
        print()


if __name__ == "__main__":
    main()
