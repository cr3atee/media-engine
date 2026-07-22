from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.parsers.models import ParsedOffer
from app.parsers.playerok_normalizer import PlayerokNormalizer


def main() -> None:
    """Print Playerok offers before and after normalization."""
    offers = [
        ParsedOffer(
            marketplace="PLAYEROK",
            external_id="  minecraft-premium  ",
            title="  Minecraft    Premium  ",
            url="  https://playerok.com/products/minecraft-premium  ",
            price=Decimal("790"),
            currency=" rub ",
            seller_id="  seller-1  ",
            seller_name="  Digital    Store  ",
        ),
        ParsedOffer(
            marketplace="playerok",
            external_id="steam-wallet",
            title="Steam   Wallet",
            url="https://playerok.com/products/steam-wallet",
            price=Decimal("1000"),
            currency="RUR",
            seller_name="Game Shop",
        ),
    ]

    normalized_offers = PlayerokNormalizer().normalize(offers)

    for before, after in zip(offers, normalized_offers, strict=True):
        print("Before:", before)
        print("After: ", after)
        print()


if __name__ == "__main__":
    main()
