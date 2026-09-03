from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if TYPE_CHECKING:
    from app.parsers.models import ParsedOffer

TMP_DIR = PROJECT_ROOT / "tmp"
GGSEL_RESPONSE_PATH = TMP_DIR / "ggsel_response.html"
PLAYEROK_RESPONSE_PATHS = (
    TMP_DIR / "playerok_response.json",
    TMP_DIR / "playerok_response.html",
    TMP_DIR / "playerok_response.txt",
)
FUNPAY_RESPONSE_PATH = TMP_DIR / "funpay_response.html"


@dataclass(slots=True, frozen=True)
class MarketplaceReadiness:
    """Offline readiness summary for one marketplace data source."""

    marketplace: str
    status: str
    raw_items: int
    parsed_offers: int
    snapshot_ready_offers: int
    notes: tuple[str, ...]
    examples: tuple[ParsedOffer, ...] = ()


def main() -> None:
    """Print the current marketplace data readiness without network calls."""
    results = (
        verify_ggsel(),
        verify_playerok(),
        verify_funpay(),
    )

    print("=== MARKETPLACE DATA READINESS ===")
    for result in results:
        print()
        print(f"Marketplace: {result.marketplace}")
        print(f"Status: {result.status}")
        print(f"Raw items: {result.raw_items}")
        print(f"Parsed offers: {result.parsed_offers}")
        print(f"Snapshot-ready offers: {result.snapshot_ready_offers}")
        print("Notes:")
        for note in result.notes:
            print(f"- {note}")
        if result.examples:
            print("Examples:")
            for offer in result.examples[:3]:
                print(
                    "- "
                    f"{offer.title or 'unknown'} | "
                    f"{offer.price or 'unknown'} {offer.currency or ''} | "
                    f"{offer.url or 'no url'}"
                )


def verify_ggsel() -> MarketplaceReadiness:
    """Verify the saved real GGSEL response against the parser contract."""
    from app.parsers.ggsel_extractor import GGSelExtractor
    from app.parsers.normalizers import OfferNormalizer

    if not GGSEL_RESPONSE_PATH.exists():
        return MarketplaceReadiness(
            marketplace="ggsel",
            status="blocked",
            raw_items=0,
            parsed_offers=0,
            snapshot_ready_offers=0,
            notes=("Saved GGSEL HTML response is missing.",),
        )

    html = GGSEL_RESPONSE_PATH.read_text(encoding="utf-8")
    raw_offers = GGSelExtractor().extract(html)
    normalizer = OfferNormalizer(marketplace="ggsel")
    parsed_offers = tuple(normalizer.normalize(offer) for offer in raw_offers)
    notes: list[str] = []

    if raw_offers:
        notes.append("Saved real GGSEL payload is extractable.")
    else:
        notes.append("Saved GGSEL payload contains no extractable offers.")

    relative_urls = sum(
        1
        for offer in parsed_offers
        if offer.url is not None and not offer.url.startswith(("http://", "https://"))
    )
    if relative_urls:
        notes.append(f"{relative_urls} parsed GGSEL offers still have relative URLs.")

    ready_offers = snapshot_ready(parsed_offers)
    return MarketplaceReadiness(
        marketplace="ggsel",
        status="ready" if ready_offers and not relative_urls else "partial",
        raw_items=len(raw_offers),
        parsed_offers=len(parsed_offers),
        snapshot_ready_offers=ready_offers,
        notes=tuple(notes),
        examples=parsed_offers[:3],
    )


def verify_playerok() -> MarketplaceReadiness:
    """Verify a saved Playerok response if one exists locally."""
    from app.parsers.playerok_extractor import PlayerokExtractor
    from app.parsers.playerok_normalizer import PlayerokNormalizer

    response_path = next(
        (path for path in PLAYEROK_RESPONSE_PATHS if path.exists()),
        None,
    )
    if response_path is None:
        return MarketplaceReadiness(
            marketplace="playerok",
            status="blocked",
            raw_items=0,
            parsed_offers=0,
            snapshot_ready_offers=0,
            notes=("Saved Playerok response is missing.",),
        )

    raw_response = response_path.read_text(encoding="utf-8")
    extracted = PlayerokExtractor().extract(raw_response)
    parsed_offers = tuple(PlayerokNormalizer().normalize(extracted))
    ready_offers = snapshot_ready(parsed_offers)
    return MarketplaceReadiness(
        marketplace="playerok",
        status="ready" if ready_offers else "partial",
        raw_items=len(extracted),
        parsed_offers=len(parsed_offers),
        snapshot_ready_offers=ready_offers,
        notes=(f"Verified saved Playerok response: {response_path.name}.",),
        examples=parsed_offers[:3],
    )


def verify_funpay() -> MarketplaceReadiness:
    """Report FunPay readiness from the current repository state."""
    if FUNPAY_RESPONSE_PATH.exists():
        return MarketplaceReadiness(
            marketplace="funpay",
            status="raw_only",
            raw_items=0,
            parsed_offers=0,
            snapshot_ready_offers=0,
            notes=(
                "Saved FunPay raw response exists.",
                "FunPay extractor and normalizer are not implemented yet.",
            ),
        )

    return MarketplaceReadiness(
        marketplace="funpay",
        status="not_implemented",
        raw_items=0,
        parsed_offers=0,
        snapshot_ready_offers=0,
        notes=(
            "FunPay raw fetcher exists, but no saved raw response is available.",
            "FunPay extractor and normalizer are not implemented yet.",
        ),
    )


def snapshot_ready(offers: tuple[ParsedOffer, ...]) -> int:
    """Count offers that contain the fields required by SnapshotBuilder."""
    return sum(
        offer.external_id is not None
        and offer.price is not None
        and offer.currency is not None
        for offer in offers
    )


if __name__ == "__main__":
    main()
