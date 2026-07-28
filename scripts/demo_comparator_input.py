from __future__ import annotations

# ruff: noqa: E402, I001

import asyncio
import sys
from collections import defaultdict
from pathlib import Path
from uuid import UUID, uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.comparator.models import MarketplaceOffer, ProductComparisonInput
from app.parsers.models import ParsedOffer


def _group_offers(
    offers: list[ParsedOffer],
) -> list[ProductComparisonInput]:
    grouped: dict[UUID | None, list[MarketplaceOffer]] = defaultdict(list)
    for offer in offers:
        grouped[offer.canonical_product_id].append(MarketplaceOffer(offer=offer))

    return [
        ProductComparisonInput(
            canonical_product_id=canonical_product_id,
            offers=tuple(items),
        )
        for canonical_product_id, items in grouped.items()
    ]


async def main() -> None:
    """Load offers from the repository provider and print comparison inputs."""
    from app.repositories.provider import create_memory_provider

    provider = create_memory_provider()

    canonical_a = uuid4()
    canonical_b = uuid4()

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
            canonical_product_id=canonical_a,
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
            canonical_product_id=canonical_a,
        ),
        ParsedOffer(
            marketplace="funpay",
            external_id="funpay-1",
            title="GTA V Account",
            url="https://funpay.com/item/1",
            price=None,
            currency=None,
            seller_id=None,
            seller_name="Seller Three",
            canonical_product_id=canonical_b,
        ),
        ParsedOffer(
            marketplace="ggsel",
            external_id="ggsel-2",
            title="Unlinked Offer",
            url="https://ggsel.net/item/2",
            price=None,
            currency=None,
            seller_id=None,
            seller_name="Seller Four",
            canonical_product_id=None,
        ),
    ]

    for offer in offers:
        await provider.offers.save(offer)

    loaded_offers = list(await provider.offers.list_all())
    comparison_inputs = _group_offers(loaded_offers)

    print(f"Loaded offers: {len(loaded_offers)}")
    print(f"Comparison inputs: {len(comparison_inputs)}")
    for item in comparison_inputs:
        print(item)


if __name__ == "__main__":
    asyncio.run(main())
