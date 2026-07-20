from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.parsers.models import RawMarketplaceOffer
from app.parsers.normalizers import OfferNormalizer


def main() -> None:
    """Normalize a fake GGSEL offer and print the ParsedOffer result."""
    raw_offer = RawMarketplaceOffer(
        id_goods=1,
        name=" Minecraft Premium ",
        url="https://example.com/item",
        seller_name="Demo Seller",
        id_section=10,
        price=790.0,
        currency="RUB",
    )

    offer = OfferNormalizer(marketplace="ggsel").normalize(raw_offer)
    print(offer)


if __name__ == "__main__":
    main()
