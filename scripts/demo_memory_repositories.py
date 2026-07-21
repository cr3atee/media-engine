from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from pprint import pprint
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer
from app.repositories.memory import (
    MemoryCanonicalProductRepository,
    MemoryOfferRepository,
    MemoryPriceHistoryRepository,
)


def main() -> None:
    """Demonstrate in-memory repository implementations."""
    product_repository = MemoryCanonicalProductRepository()
    offer_repository = MemoryOfferRepository()
    price_history_repository = MemoryPriceHistoryRepository()

    minecraft = CanonicalProduct(
        id=uuid4(),
        name="Minecraft Premium",
        category="games",
        aliases=("minecraft account",),
    )
    gta = CanonicalProduct(
        id=uuid4(),
        name="Grand Theft Auto V",
        category="games",
        aliases=("gta 5",),
    )

    product_repository.save(minecraft)
    product_repository.save(gta)

    offer_repository.save(
        ParsedOffer(
            marketplace="ggsel",
            external_id="ggsel-1",
            title="Minecraft Premium",
            url="https://example.com/ggsel/minecraft",
            price=Decimal("790"),
            currency="RUB",
            canonical_product_id=minecraft.id,
        ),
    )
    offer_repository.save(
        ParsedOffer(
            marketplace="playerok",
            external_id="playerok-1",
            title="GTA5 Account",
            url="https://example.com/playerok/gta5",
            price=Decimal("1200"),
            currency="RUB",
            canonical_product_id=gta.id,
        ),
    )

    print("Canonical products:")
    pprint(product_repository.list_all())
    print()
    print("Product by ID:")
    pprint(product_repository.get_by_id(minecraft.id))
    print()
    print("Offers:")
    pprint(offer_repository.list_all())
    print()
    print("Price history repository:")
    print(price_history_repository.__class__.__name__)


if __name__ == "__main__":
    main()
