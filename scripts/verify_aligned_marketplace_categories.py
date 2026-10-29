"""Verify aligned real marketplace categories with existing adapter boundaries."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from collections.abc import Awaitable, Callable
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
from app.parsers.source_snapshot import SourceSnapshotEvidence  # noqa: E402
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
    source_items_seen: int | None = None
    source_snapshot_complete: bool = False
    source_snapshot_reason: str = "Source completeness evidence was not collected."


type MarketplaceCategoryFetcher = Callable[
    [HttpClient],
    Awaitable[MarketplaceCategoryBatch],
]


@dataclass(slots=True, frozen=True)
class MarketplaceCategoryFetchResult:
    """One isolated marketplace fetch outcome for review evidence."""

    marketplace: str
    batch: MarketplaceCategoryBatch | None = None
    error_code: str | None = None
    error_summary: str | None = None

    @property
    def succeeded(self) -> bool:
        """Return whether the marketplace produced a usable batch."""
        return self.batch is not None and self.error_code is None


async def main() -> int:
    """Fetch aligned categories and report current deterministic match evidence."""
    _configure_stdout()
    results = await fetch_aligned_marketplace_categories_isolated()
    batches = tuple(
        result.batch
        for result in results
        if result.succeeded and result.batch is not None
    )
    failures = tuple(result for result in results if not result.succeeded)

    print("=== REAL ALIGNED CATEGORY INPUT ===")
    for result in results:
        if result.batch is None:
            print(
                f"{result.marketplace}: failed "
                f"[{result.error_code or 'UnknownError'}] "
                f"{result.error_summary or 'Marketplace request failed.'}"
            )
            continue
        batch = result.batch
        source_items_seen = (
            batch.source_items_seen
            if batch.source_items_seen is not None
            else len(batch.offers)
        )
        print(
            f"{batch.marketplace}: source-seen={source_items_seen}, "
            f"source-total={batch.source_total}, "
            f"parsed={len(batch.offers)}, "
            f"snapshot-ready={len(batch.snapshot_ready_offers)}, "
            f"complete={batch.source_snapshot_complete}"
        )
        print(f"  completeness: {batch.source_snapshot_reason}")

    if len(batches) < 2:
        print("At least two successful marketplace sources are required.")
        return 1

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
        print(
            "  "
            f"id={candidate.left_external_id or 'unknown'} | "
            f"price={candidate.left_price} {candidate.left_currency or ''} | "
            f"seller={candidate.left_seller_name or 'unknown'}"
        )
        print(f"  url={candidate.left_url or 'unknown'}")
        print(f"  {candidate.right_marketplace}: {candidate.right_title}")
        print(
            "  "
            f"id={candidate.right_external_id or 'unknown'} | "
            f"price={candidate.right_price} {candidate.right_currency or ''} | "
            f"seller={candidate.right_seller_name or 'unknown'}"
        )
        print(f"  url={candidate.right_url or 'unknown'}")

    print("\n=== TOP CANDIDATES PER SOURCE PAIR ===")
    for pair in report.top_candidates_by_marketplace_pair:
        print(f"\n{pair.left_marketplace}/{pair.right_marketplace}")
        for candidate in pair.candidates:
            print(f"- {candidate.similarity:.3f} [{candidate.decision.value}]")
            print(
                f"  {candidate.left_external_id or 'unknown'} | "
                f"{candidate.left_price} {candidate.left_currency or ''} | "
                f"seller={candidate.left_seller_name or 'unknown'}"
            )
            print(f"  {candidate.left_title}")
            print(f"  {candidate.left_url or 'unknown'}")
            print(
                f"  {candidate.right_external_id or 'unknown'} | "
                f"{candidate.right_price} {candidate.right_currency or ''} | "
                f"seller={candidate.right_seller_name or 'unknown'}"
            )
            print(f"  {candidate.right_title}")
            print(f"  {candidate.right_url or 'unknown'}")

    print("\nCategory alignment is source evidence, not product identity proof.")
    if failures:
        print(
            "Status: incomplete; one or more marketplaces were unavailable, "
            "so this run is not full three-source evidence."
        )
        return 1
    incomplete_snapshots = tuple(
        batch.marketplace for batch in batches if not batch.source_snapshot_complete
    )
    if incomplete_snapshots:
        print(
            "Status: all three sources fetched; missing-offer reconciliation "
            "remains disabled for partial sources: "
            f"{', '.join(incomplete_snapshots)}."
        )
    else:
        print("Status: complete three-source snapshot evidence.")
    return 0


async def fetch_aligned_marketplace_categories() -> tuple[
    MarketplaceCategoryBatch, ...
]:
    """Fetch all aligned categories or fail when any source is unavailable."""
    results = await fetch_aligned_marketplace_categories_isolated()
    failures = tuple(result for result in results if not result.succeeded)
    if failures:
        details = ", ".join(
            f"{result.marketplace}:{result.error_code or 'UnknownError'}"
            for result in failures
        )
        raise RuntimeError(f"Aligned marketplace fetch failed: {details}")
    return tuple(result.batch for result in results if result.batch is not None)


async def fetch_aligned_marketplace_categories_isolated() -> tuple[
    MarketplaceCategoryFetchResult, ...
]:
    """Fetch each aligned category without hiding successful source evidence."""
    async with HttpClient(timeout=30.0) as http_client:
        return tuple(
            await asyncio.gather(
                _capture_fetch("ggsel", _fetch_ggsel, http_client),
                _capture_fetch("playerok", _fetch_playerok, http_client),
                _capture_fetch("funpay", _fetch_funpay, http_client),
            )
        )


async def _capture_fetch(
    marketplace: str,
    fetch: MarketplaceCategoryFetcher,
    http_client: HttpClient,
) -> MarketplaceCategoryFetchResult:
    try:
        batch = await fetch(http_client)
    except Exception as exc:
        return MarketplaceCategoryFetchResult(
            marketplace=marketplace,
            error_code=type(exc).__name__,
            error_summary=_safe_error_summary(exc),
        )
    return MarketplaceCategoryFetchResult(
        marketplace=marketplace,
        batch=batch,
    )


def _safe_error_summary(error: Exception) -> str:
    summary = re.sub(r"<[^>]*>", " ", str(error))
    summary = " ".join(summary.split())
    if not summary:
        return "Marketplace request failed."
    http_status = re.search(r"\bHTTP [1-5]\d{2}\b", summary)
    if http_status is not None:
        return summary[: http_status.end()]
    return summary[:240]


async def _fetch_ggsel(http_client: HttpClient) -> MarketplaceCategoryBatch:
    fetcher = GGSelFetcher(http_client)
    html = await fetcher.fetch_html(GGSEL_CATEGORY_URL)
    extraction = GGSelExtractor().extract_with_evidence(html)
    raw_offers = extraction.items
    normalizer = OfferNormalizer(marketplace="ggsel")
    offers = tuple(normalizer.normalize(offer) for offer in raw_offers)
    source_total = extraction.evidence.expected_items or len(raw_offers)
    return _batch("ggsel", source_total, offers, extraction.evidence)


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
    return _batch(
        "playerok",
        source_total,
        offers,
        SourceSnapshotEvidence(
            source_items=len(extracted),
            parsed_items=len(offers),
            expected_items=source_total,
            complete=source_total == len(extracted) == len(offers),
            reason=(
                "Playerok declared total and extracted item count match."
                if source_total == len(extracted) == len(offers)
                else (
                    f"Playerok returned {len(extracted)} of {source_total} "
                    "declared items."
                )
            ),
        ),
    )


async def _fetch_funpay(http_client: HttpClient) -> MarketplaceCategoryBatch:
    fetcher = FunPayFetcher(http_client)
    html = await fetcher.fetch(FUNPAY_CATEGORY_URL)
    extraction = FunPayExtractor().extract_with_evidence(html)
    offers = tuple(FunPayNormalizer().normalize(list(extraction.items)))
    return _batch(
        "funpay",
        extraction.evidence.source_items,
        offers,
        extraction.evidence,
    )


def _batch(
    marketplace: str,
    source_total: int,
    offers: tuple[ParsedOffer, ...],
    evidence: SourceSnapshotEvidence | None = None,
) -> MarketplaceCategoryBatch:
    return MarketplaceCategoryBatch(
        marketplace=marketplace,
        source_total=source_total,
        offers=offers,
        snapshot_ready_offers=tuple(
            offer for offer in offers if _is_snapshot_ready(offer)
        ),
        source_items_seen=(
            evidence.source_items if evidence is not None else len(offers)
        ),
        source_snapshot_complete=(evidence.complete if evidence is not None else False),
        source_snapshot_reason=(
            evidence.reason
            if evidence is not None
            else "Source completeness evidence was not collected."
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
