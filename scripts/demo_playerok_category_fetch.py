from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

MINECRAFT_GAME_ID = "1ecc48ce-4f1a-6533-28cc-9d8eecf47287"
MINECRAFT_KEYS_CATEGORY_ID = "1eeb53e1-112a-6b20-fffc-80e79d6ff930"
PAGE_SIZE = 20


async def main() -> None:
    """Fetch and verify one real Playerok category without persistence."""
    _configure_stdout()
    from app.core.http_client import HttpClient
    from app.parsers.playerok_extractor import PlayerokExtractor
    from app.parsers.playerok_fetcher import PlayerokFetcher, PlayerokFetchError
    from app.parsers.playerok_normalizer import PlayerokNormalizer

    try:
        async with HttpClient(timeout=30.0) as http_client:
            fetcher = PlayerokFetcher(http_client)
            raw_response = await fetcher.fetch_items(
                first=PAGE_SIZE,
                game_id=MINECRAFT_GAME_ID,
                game_category_id=MINECRAFT_KEYS_CATEGORY_ID,
            )
    except PlayerokFetchError as exc:
        print(f"Playerok category fetch failed: {exc}")
        raise SystemExit(1) from exc

    payload = _load_json_object(raw_response)
    source_total = _read_source_total(payload)
    extracted = PlayerokExtractor().extract(raw_response)
    normalized = PlayerokNormalizer().normalize(extracted)
    snapshot_ready = [
        offer
        for offer in normalized
        if offer.external_id is not None
        and offer.title is not None
        and offer.url is not None
        and offer.price is not None
        and offer.currency is not None
    ]

    print("Playerok category: Minecraft / Keys")
    print(f"HTTP status: {fetcher.last_status_code}")
    print(f"Content type: {fetcher.last_content_type}")
    print(f"Source total: {source_total}")
    print(f"Fetched page: {len(extracted)}")
    print(f"Snapshot-ready: {len(snapshot_ready)}")

    for index, offer in enumerate(snapshot_ready[:5], start=1):
        print(f"\n{index}. {offer.title}")
        print(f"   Price: {offer.price} {offer.currency}")
        print(f"   URL: {offer.url}")

    if not normalized or len(snapshot_ready) != len(normalized):
        msg = "Playerok category response is empty or not snapshot-ready"
        raise RuntimeError(msg)


def _load_json_object(raw_response: str) -> dict[str, Any]:
    payload: object = json.loads(raw_response)
    if not isinstance(payload, dict):
        msg = "Playerok returned a non-object JSON payload"
        raise RuntimeError(msg)
    return payload


def _read_source_total(payload: dict[str, Any]) -> int:
    data = payload.get("data")
    items = data.get("items") if isinstance(data, dict) else None
    total = items.get("totalCount") if isinstance(items, dict) else None
    if not isinstance(total, int):
        msg = "Playerok response does not contain data.items.totalCount"
        raise RuntimeError(msg)
    return total


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")


if __name__ == "__main__":
    asyncio.run(main())
