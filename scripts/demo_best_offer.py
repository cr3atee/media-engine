from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

from decimal import Decimal

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    """Group offers and select the best offer in each comparison group."""
    from app.comparator.grouping import OfferGroupingService
    from app.comparator.models import MarketplaceOffer
    from app.comparator.selector import BestOfferSelector
    from app.models.canonical_product import CanonicalProduct
    from app.parsers.models import ParsedOffer
    from app.repositories.provider import create_memory_provider

    provider = create_memory_provider()

    minecraft_id = uuid4()
    gta_id = uuid4()
    cs2_id = uuid4()

    provider.canonical_products.save(
        CanonicalProduct(
            id=minecraft_id,
            name="Minecraft Premium",
            category=None,
            aliases=("minecraft",),
        ),
    )
    provider.canonical_products.save(
        CanonicalProduct(
            id=gta_id,
            name="GTA V Account",
            category=None,
            aliases=("gta v", "gta5"),
        ),
    )
    provider.canonical_products.save(
        CanonicalProduct(
            id=cs2_id,
            name="Counter Strike 2 Prime",
            category=None,
            aliases=("cs2",),
        ),
    )

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
            canonical_product_id=minecraft_id,
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
            canonical_product_id=minecraft_id,
        ),
        ParsedOffer(
            marketplace="ggsel",
            external_id="ggsel-2",
            title="GTA V Account",
            url="https://ggsel.net/item/2",
            price=Decimal("15"),
            currency="USD",
            seller_id=None,
            seller_name="Seller Three",
            canonical_product_id=gta_id,
        ),
        ParsedOffer(
            marketplace="playerok",
            external_id="playerok-2",
            title="GTA V Account",
            url="https://playerok.com/item/2",
            price=Decimal("1200"),
            currency="RUB",
            seller_id=None,
            seller_name="Seller Four",
            canonical_product_id=gta_id,
        ),
        ParsedOffer(
            marketplace="funpay",
            external_id="funpay-1",
            title="Counter Strike 2 Prime",
            url="https://funpay.com/item/1",
            price=Decimal("450"),
            currency="RUB",
            seller_id=None,
            seller_name="Seller Five",
            canonical_product_id=cs2_id,
        ),
    ]

    for offer in offers:
        provider.offers.save(offer)

    grouping_service = OfferGroupingService()
    selector = BestOfferSelector()

    grouped = grouping_service.group(
        [MarketplaceOffer(offer=offer) for offer in provider.offers.list_all()],
        provider.canonical_products.list_all(),
    )
    product_index = {
        product.id: product for product in provider.canonical_products.list_all()
    }

    for group in grouped:
        selection = selector.select(group)
        print("Canonical Product:")
        if group.canonical_product_id is None:
            print("  <unmatched>")
        else:
            print(f"  {product_index[group.canonical_product_id].name}")

        print("All marketplace offers:")
        for item in group.offers:
            offer = item.offer
            print(
                f"  - {offer.marketplace}: {offer.title} "
                f"{offer.price} {offer.currency}",
            )

        print("Selected best offer:")
        if selection.selected_offer is None:
            print("  None")
        else:
            offer = selection.selected_offer.offer
            print(
                f"  {offer.marketplace}: {offer.title} "
                f"{offer.price} {offer.currency}",
            )

        print(f"Reason: {selection.reason}")
        print()


if __name__ == "__main__":
    main()
