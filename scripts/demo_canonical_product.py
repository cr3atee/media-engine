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


def main() -> None:
    """Create one canonical product and link offers from several marketplaces."""
    canonical_product = CanonicalProduct(
        id=uuid4(),
        name="Minecraft Premium",
        category="games",
        aliases=("Minecraft account", "Minecraft Java"),
    )
    offers = [
        ParsedOffer(
            marketplace="ggsel",
            external_id="ggsel-1",
            title="Minecraft Premium",
            url="https://example.com/ggsel/minecraft",
            price=Decimal("790"),
            currency="RUB",
            canonical_product_id=canonical_product.id,
        ),
        ParsedOffer(
            marketplace="playerok",
            external_id="playerok-1",
            title="Minecraft Premium Account",
            url="https://example.com/playerok/minecraft",
            price=Decimal("810"),
            currency="RUB",
            canonical_product_id=canonical_product.id,
        ),
        ParsedOffer(
            marketplace="funpay",
            external_id="funpay-1",
            title="Minecraft Java Premium",
            url="https://example.com/funpay/minecraft",
            price=Decimal("800"),
            currency="RUB",
            canonical_product_id=canonical_product.id,
        ),
    ]

    print("Canonical product:")
    pprint(canonical_product)
    print()
    print("Linked offers:")
    for offer in offers:
        pprint(offer)


if __name__ == "__main__":
    main()
