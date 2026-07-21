from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.repositories import (
    BaseRepository,
    CanonicalProductRepository,
    OfferRepository,
    PriceHistoryRepository,
)


def main() -> None:
    """Print repository contract class names to verify imports."""
    repositories = (
        BaseRepository,
        CanonicalProductRepository,
        OfferRepository,
        PriceHistoryRepository,
    )
    for repository in repositories:
        print(repository.__name__)


if __name__ == "__main__":
    main()
