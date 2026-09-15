"""Verify aligned real marketplace categories with existing adapter boundaries."""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.http_client import HttpClient  # noqa: E402
from app.parsers.funpay_extractor import FunPayExtractor  # noqa: E402
from app.parsers.funpay_fetcher import FunPayFetcher  # noqa: E402
from app.parsers.funpay_normalizer import FunPayNormalizer  # noqa: E402
from app.parsers.ggsel_extractor import GGSelExtractor  # noqa: E402
from app.parsers.ggsel_fetcher import GGSelFetcher  # noqa: E402
from app.parsers.models import ParsedOffer  # noqa: E402
from app.parsers.normalizers import OfferNormalizer  # noqa: E402
from app.parsers.playerok_extractor import PlayerokExtractor  # noqa: E402
from app.parsers.playerok_fetcher import PlayerokFetcher  # noqa: E402
from app.parsers.playerok_normalizer import PlayerokNormalizer  # noqa: E402
from scripts.analyze_cross_marketplace_matching import (  # noqa: E402
    analyze_cross_marketplace_matching,
)

GGSEL_CATEGORY_URL = "https://ggsel.net/en/catalog/minecraft-keys-pc"
FUNPAY_CATEGORY_URL = "https://funpay.com/lots/1015/"
PLAYEROK_GAME_ID = "1ecc48ce-4f1a-6533-28cc-9d8eecf47287"
PLAYEROK_CATEGORY_ID = "1eeb53e1-112a-6b20-fffc-80e79d6ff930"
PLAYEROK_PAGE_SIZE = 20


@dataclass(slots=True, frozen=True)
class MarketplaceCategoryBatch:
    """Observed normalized offers from one real marketplace category request."""

    marketplace: str
    source_total: int
    offers: tuple[ParsedOffer, ...]
    snapshot_ready_offers: tuple[ParsedOffer, ...]


async def main() -> int:
    """Fetch aligned categories and report current deterministic match evidence."""
    _configure_stdout()
    try:
        async with HttpClient(timeout=30.0) as http_client:
            batches = (
                await _fetch_ggsel(http_client),
                await _fetch_playerok(http_client),
                await _fetch_funpay(http_client),
            )
    except Exception as exc:
        print(f"Aligned category verification failed: {type(exc).__name__}: {exc}")
        return 1

    print("=== REAL ALIGNED CATEGORY INPUT ===")
    for batch in batches:
        print(
            f"{batch.marketplace}: source={batch.source_total}, "
            f"parsed={len(batch.offers)}, "
            f"snapshot-ready={len(batch.snapshot_ready_offers)}"
        )

    empty_sources = [
        batch.marketplace for batch in batches if not batch.snapshot_ready_offers
    ]
    if empty_sources:
        print(f"No snapshot-ready data: {', '.join(empty_sources)}")
        return 1

    report = analyze_cross_marketplace_matching(
        {batch.marketplace: batch.snapshot_ready_offers for batch in batches},
        top_limit=10,
    )
    print("\n=== DETERMINISTIC MATCHING EVIDENCE ===")
    print(f"Offers: {report.offer_count}")
    print(f"Cross-marketplace pairs: {report.pair_count}")
    print(f"AUTO_MATCH: {report.auto_match_count}")
    print(f"REVIEW: {report.review_count}")
    print(f"NO_MATCH: {report.no_match_count}")
    print(f"Highest similarity: {report.highest_similarity:.3f}")
    print("\nHighest-scoring candidates:")
    for candidate in report.top_candidates:
        print(
            f"- {candidate.similarity:.3f} [{candidate.decision.value}] "
            f"{candidate.left_marketplace}: {candidate.left_title}"
        )
        print(f"  {candidate.right_marketplace}: {candidate.right_title}")

    print("\nCategory alignment is source evidence, not product identity proof.")
    return 0


async def _fetch_ggsel(http_client: HttpClient) -> MarketplaceCategoryBatch:
    fetcher = GGSelFetcher(http_client)
    html = await fetcher.fetch_html(GGSEL_CATEGORY_URL)
    raw_offers = GGSelExtractor().extract(html)
    normalizer = OfferNormalizer(marketplace="ggsel")
    offers = tuple(normalizer.normalize(offer) for offer in raw_offers)
    return _batch("ggsel", len(raw_offers), offers)


async def _fetch_playerok(http_client: HttpClient) -> MarketplaceCategoryBatch:
    fetcher = PlayerokFetcher(http_client)
    raw_response = await fetcher.fetch_items(
        first=PLAYEROK_PAGE_SIZE,
        game_id=PLAYEROK_GAME_ID,
        game_category_id=PLAYEROK_CATEGORY_ID,
    )
    source_total = _playerok_source_total(raw_response)
    extracted = PlayerokExtractor().extract(raw_response)
    offers = tuple(PlayerokNormalizer().normalize(extracted))
    return _batch("playerok", source_total, offers)


async def _fetch_funpay(http_client: HttpClient) -> MarketplaceCategoryBatch:
    fetcher = FunPayFetcher(http_client)
    html = await fetcher.fetch(FUNPAY_CATEGORY_URL)
    extracted = FunPayExtractor().extract(html)
    offers = tuple(FunPayNormalizer().normalize(extracted))
    return _batch("funpay", len(extracted), offers)


def _batch(
    marketplace: str,
    source_total: int,
    offers: tuple[ParsedOffer, ...],
) -> MarketplaceCategoryBatch:
    return MarketplaceCategoryBatch(
        marketplace=marketplace,
        source_total=source_total,
        offers=offers,
        snapshot_ready_offers=tuple(
            offer for offer in offers if _is_snapshot_ready(offer)
        ),
    )


def _is_snapshot_ready(offer: ParsedOffer) -> bool:
    return (
        offer.external_id is not None
        and offer.title is not None
        and offer.url is not None
        and offer.price is not None
        and offer.currency is not None
    )


def _playerok_source_total(raw_response: str) -> int:
    payload: object = json.loads(raw_response)
    if not isinstance(payload, dict):
        raise ValueError("Playerok response is not a JSON object")
    data: Any = payload.get("data")
    items: Any = data.get("items") if isinstance(data, dict) else None
    total: Any = items.get("totalCount") if isinstance(items, dict) else None
    if not isinstance(total, int):
        raise ValueError("Playerok response has no data.items.totalCount")
    return total


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
