from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

HTML_RESPONSE_PATH = PROJECT_ROOT / "tmp" / "ggsel_response.html"


async def main() -> None:
    """Store and read a price snapshot built from a saved GGSEL response."""
    from app.parsers.ggsel_extractor import GGSelExtractor
    from app.parsers.normalizers import OfferNormalizer
    from app.repositories.provider import create_memory_provider
    from app.services.snapshot_builder import SnapshotBuilder

    if not HTML_RESPONSE_PATH.exists():
        print(f"GGSEL response is unavailable: {HTML_RESPONSE_PATH}")
        return

    raw_response = HTML_RESPONSE_PATH.read_text(encoding="utf-8")
    raw_offers = GGSelExtractor().extract(raw_response)
    if not raw_offers:
        print("GGSEL response contains no extractable offers.")
        return

    parsed_offer = OfferNormalizer(marketplace="ggsel").normalize(raw_offers[0])
    snapshot = SnapshotBuilder().build(parsed_offer)

    price_history = create_memory_provider().price_history
    await price_history.add(snapshot)
    history_entry = await price_history.get_last(
        snapshot.marketplace,
        snapshot.external_id,
    )
    history = await price_history.get_history(
        snapshot.marketplace,
        snapshot.external_id,
    )

    print("Snapshot:")
    print(snapshot)
    print()
    print("History entry:")
    print(history_entry)
    print()
    print(f"Current history size: {len(history)}")


if __name__ == "__main__":
    asyncio.run(main())
