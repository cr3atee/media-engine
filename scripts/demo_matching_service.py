from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.matching.service import MatchingService
from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer


def main() -> None:
    """Run a small matching service demonstration."""
    offer = ParsedOffer(
        marketplace="ggsel",
        external_id="ggsel-1",
        title="MC Premium Steam Account",
        url="https://example.com/ggsel/minecraft",
        price=Decimal("790"),
        currency="RUB",
    )
    candidates = (
        CanonicalProduct(
            id=uuid4(),
            name="Minecraft Premium",
            category="games",
            aliases=("minecraft account",),
        ),
        CanonicalProduct(
            id=uuid4(),
            name="Grand Theft Auto V",
            category="games",
            aliases=("gta 5",),
        ),
        CanonicalProduct(
            id=uuid4(),
            name="Counter Strike 2",
            category="games",
            aliases=("cs2",),
        ),
    )

    result = MatchingService().match(offer, candidates)

    print(f"Best match: {result.canonical_product.name if result.canonical_product else None}")
    print(f"Similarity: {result.similarity:.2f}")
    print(f"Decision: {result.decision.value}")


if __name__ == "__main__":
    main()
