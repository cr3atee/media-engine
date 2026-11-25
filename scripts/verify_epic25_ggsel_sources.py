"""Verify real GGSEL evidence for the three-product EPIC 25 assortment."""

# ruff: noqa: E402
from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.http_client import HttpClient  # noqa: E402
from app.parsers.ggsel_extractor import GGSelExtractor  # noqa: E402
from app.parsers.ggsel_fetcher import GGSelFetcher, GGSelFetchError  # noqa: E402
from app.parsers.models import ParsedOffer  # noqa: E402
from app.parsers.normalizers import OfferNormalizer  # noqa: E402
from app.services.subscription_candidate_rules import (  # noqa: E402
    LAUNCH_PRODUCTS as LAUNCH_PRODUCTS,
)
from app.services.subscription_candidate_rules import (
    LaunchProductSpec as LaunchProductSpec,
)
from app.services.subscription_candidate_rules import (
    find_exact_month_candidates as find_exact_month_candidates,
)

LIVE_GUARD = "I_UNDERSTAND_THIS_CONTACTS_GGSEL"
LIVE_GUARD_ENV = "EPIC25_GGSEL_LIVE_VERIFY"


@dataclass(slots=True, frozen=True)
class VerifiedSource:
    """Hold one read-only source verification result."""

    spec: LaunchProductSpec
    source_total: int
    candidate_count: int
    offer: ParsedOffer
    url_status: int


class Epic25SourceVerificationError(RuntimeError):
    """Raised when live GGSEL evidence is incomplete or ambiguous."""


def select_candidate(
    spec: LaunchProductSpec,
    offers: tuple[ParsedOffer, ...],
) -> ParsedOffer:
    """Select a deterministic evidence example without ranking its price."""
    candidates = find_exact_month_candidates(spec, offers)
    if not candidates:
        raise Epic25SourceVerificationError(
            f"{spec.name}: no exact one-month GGSEL candidate was found."
        )
    return candidates[0]


def validate_snapshot_ready_offer(offer: ParsedOffer) -> None:
    """Require every universal field consumed by SnapshotBuilder."""
    missing = [
        field
        for field, value in (
            ("external_id", offer.external_id),
            ("title", offer.title),
            ("url", offer.url),
            ("price", offer.price),
            ("currency", offer.currency),
            ("seller_name", offer.seller_name),
            ("source_category_id", offer.source_category_id),
        )
        if value is None
    ]
    if missing:
        raise Epic25SourceVerificationError(
            f"GGSEL offer is not snapshot-ready: {', '.join(missing)}."
        )

    assert offer.url is not None
    parsed_url = urlsplit(offer.url)
    if parsed_url.scheme != "https" or parsed_url.hostname not in {
        "ggsel.net",
        "www.ggsel.net",
    }:
        raise Epic25SourceVerificationError(
            "GGSEL offer URL does not use the trusted HTTPS host."
        )


async def main() -> int:
    """Fetch and verify all three launch sources without mutating application state."""
    _configure_stdout()
    if os.getenv(LIVE_GUARD_ENV, "") != LIVE_GUARD:
        print(f"SKIP: set {LIVE_GUARD_ENV}={LIVE_GUARD} for live verification.")
        return 2

    try:
        async with HttpClient(timeout=30.0, max_retries=2) as http_client:
            results = await fetch_verified_launch_sources(http_client)
    except (Epic25SourceVerificationError, GGSelFetchError) as exc:
        print(f"FAIL: {exc}")
        return 1

    print("=== EPIC 25 GGSEL SOURCE EVIDENCE ===")
    for result in results:
        offer = result.offer
        print(f"\n{result.spec.name}")
        print(f"Category products: {result.source_total}")
        print(f"Exact one-month candidates: {result.candidate_count}")
        print(f"Offer ID: {offer.external_id}")
        print(f"Title: {offer.title}")
        print(f"Seller: {offer.seller_name}")
        print(f"Price: {offer.price} {offer.currency}")
        print(f"URL: {offer.url}")
        print(f"URL status: {result.url_status}")

    print("\nPASS: 3/3 launch products have current read-only GGSEL evidence.")
    print("No offers, products, review decisions, or prices were persisted.")
    return 0


async def fetch_verified_launch_sources(
    http_client: HttpClient,
) -> tuple[VerifiedSource, ...]:
    """Return source-backed launch examples after complete live verification."""
    fetcher = GGSelFetcher(http_client)
    extractor = GGSelExtractor()
    normalizer = OfferNormalizer(marketplace="ggsel")
    results: list[VerifiedSource] = []

    for spec in LAUNCH_PRODUCTS:
        source = await fetcher.fetch_complete_category(spec.category_url)
        extracted = extractor.extract_source_items(source)
        if not extracted.evidence.complete:
            raise Epic25SourceVerificationError(
                f"{spec.name}: {extracted.evidence.reason}"
            )

        offers = tuple(normalizer.normalize(item) for item in extracted.items)
        candidates = find_exact_month_candidates(spec, offers)
        selected = select_candidate(spec, offers)
        validate_snapshot_ready_offer(selected)
        assert selected.url is not None
        url_response = await http_client.get(
            selected.url,
            headers=GGSelFetcher.CATEGORY_HEADERS,
        )
        if url_response.status_code >= 400:
            raise Epic25SourceVerificationError(
                f"{spec.name}: selected source URL returned "
                f"HTTP {url_response.status_code}."
            )

        results.append(
            VerifiedSource(
                spec=spec,
                source_total=len(offers),
                candidate_count=len(candidates),
                offer=selected,
                url_status=url_response.status_code,
            )
        )

    return tuple(results)


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
