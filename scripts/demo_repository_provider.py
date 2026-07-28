from __future__ import annotations

# ruff: noqa: E402
import asyncio
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
from app.repositories.provider import create_memory_provider


async def main() -> None:
    """Demonstrate repository access through RepositoryProvider."""
    provider = create_memory_provider()

    product = CanonicalProduct(
        id=uuid4(),
        name="Minecraft Premium",
        category="games",
        aliases=("minecraft account",),
    )
    await provider.canonical_products.save(product)
    await provider.offers.save(
        ParsedOffer(
            marketplace="ggsel",
            external_id="ggsel-1",
            title="Minecraft Premium",
            url="https://example.com/ggsel/minecraft",
            price=Decimal("790"),
            currency="RUB",
            canonical_product_id=product.id,
        ),
    )

    print("Canonical products:")
    pprint(await provider.canonical_products.list_all())
    print()
    print("Product by ID:")
    pprint(await provider.canonical_products.get_by_id(product.id))
    print()
    print("Offers:")
    pprint(await provider.offers.list_all())
    print()
    print("Price history repository:")
    print(provider.price_history.__class__.__name__)


if __name__ == "__main__":
    asyncio.run(main())
