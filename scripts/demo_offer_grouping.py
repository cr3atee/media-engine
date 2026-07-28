from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


async def main() -> None:
    """Load repository data and print grouped comparison inputs."""
    from app.comparator.grouping import OfferGroupingService
    from app.comparator.models import MarketplaceOffer
    from app.models.canonical_product import CanonicalProduct
    from app.parsers.models import ParsedOffer
    from app.repositories.provider import create_memory_provider

    provider = create_memory_provider()

    minecraft_id = uuid4()
    gta_id = uuid4()

    await provider.canonical_products.save(
        CanonicalProduct(
            id=minecraft_id,
            name="Minecraft Premium",
            category=None,
            aliases=("minecraft",),
        ),
    )
    await provider.canonical_products.save(
        CanonicalProduct(
            id=gta_id,
            name="GTA V Account",
            category=None,
            aliases=("gta v", "gta5"),
        ),
    )

    offers = [
        ParsedOffer(
            marketplace="ggsel",
            external_id="ggsel-1",
            title="Minecraft Premium",
            url="https://ggsel.net/item/1",
            price=None,
            currency=None,
            seller_id=None,
            seller_name="Seller One",
            canonical_product_id=minecraft_id,
        ),
        ParsedOffer(
            marketplace="playerok",
            external_id="playerok-1",
            title="Minecraft Premium",
            url="https://playerok.com/item/1",
            price=None,
            currency=None,
            seller_id=None,
            seller_name="Seller Two",
            canonical_product_id=minecraft_id,
        ),
        ParsedOffer(
            marketplace="ggsel",
            external_id="ggsel-2",
            title="GTA V Account",
            url="https://ggsel.net/item/2",
            price=None,
            currency=None,
            seller_id=None,
            seller_name="Seller Three",
            canonical_product_id=gta_id,
        ),
        ParsedOffer(
            marketplace="funpay",
            external_id="funpay-1",
            title="Unmatched Offer",
            url="https://funpay.com/item/1",
            price=None,
            currency=None,
            seller_id=None,
            seller_name="Seller Four",
            canonical_product_id=None,
        ),
    ]

    for offer in offers:
        await provider.offers.save(offer)

    grouping_service = OfferGroupingService()
    stored_offers = await provider.offers.list_all()
    canonical_products = await provider.canonical_products.list_all()
    grouped = grouping_service.group(
        [MarketplaceOffer(offer=offer) for offer in stored_offers],
        canonical_products,
    )

    product_index = {product.id: product for product in canonical_products}

    for group in grouped:
        if group.canonical_product_id is None:
            print("Canonical Product: <unmatched>")
        else:
            product = product_index[group.canonical_product_id]
            print(f"Canonical Product: {product.name}")

        for item in group.offers:
            print(f"  {item.offer.marketplace}: {item.offer.title}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
