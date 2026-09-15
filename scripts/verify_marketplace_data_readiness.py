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


@dataclass(slots=True, frozen=True)
class LoadedMarketplacePayload:
    """Raw item count and every normalized offer loaded from a saved payload."""

    marketplace: str
    raw_items: int
    offers: tuple[ParsedOffer, ...]


def main() -> None:
    """Print the current marketplace data readiness without network calls."""
    _configure_stdout()
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
    if not GGSEL_RESPONSE_PATH.exists():
        return MarketplaceReadiness(
            marketplace="ggsel",
            status="blocked",
            raw_items=0,
            parsed_offers=0,
            snapshot_ready_offers=0,
            notes=("Saved GGSEL HTML response is missing.",),
        )

    payload = load_ggsel_payload()
    parsed_offers = payload.offers
    notes: list[str] = []

    if parsed_offers:
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
        raw_items=payload.raw_items,
        parsed_offers=len(parsed_offers),
        snapshot_ready_offers=ready_offers,
        notes=tuple(notes),
        examples=parsed_offers[:3],
    )


def verify_playerok() -> MarketplaceReadiness:
    """Verify a saved Playerok response if one exists locally."""
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

    payload = load_playerok_payload(response_path)
    parsed_offers = payload.offers
    ready_offers = snapshot_ready(parsed_offers)
    return MarketplaceReadiness(
        marketplace="playerok",
        status="ready" if ready_offers else "partial",
        raw_items=payload.raw_items,
        parsed_offers=len(parsed_offers),
        snapshot_ready_offers=ready_offers,
        notes=(
            f"Verified saved Playerok response: {response_path.name}.",
            "Playerok normalizer applies the source-backed RUB default.",
        ),
        examples=parsed_offers[:3],
    )


def verify_funpay() -> MarketplaceReadiness:
    """Report FunPay readiness from the current repository state."""
    if FUNPAY_RESPONSE_PATH.exists():
        payload = load_funpay_payload()
        parsed_offers = payload.offers
        ready_offers = snapshot_ready(parsed_offers)
        return MarketplaceReadiness(
            marketplace="funpay",
            status="ready" if ready_offers else "partial",
            raw_items=payload.raw_items,
            parsed_offers=len(parsed_offers),
            snapshot_ready_offers=ready_offers,
            notes=("Saved FunPay raw response exists.",),
            examples=parsed_offers[:3],
        )

    return MarketplaceReadiness(
        marketplace="funpay",
        status="blocked",
        raw_items=0,
        parsed_offers=0,
        snapshot_ready_offers=0,
        notes=(
            "FunPay fetcher/extractor/normalizer exist.",
            "Saved FunPay raw response is not available.",
        ),
    )


def load_saved_marketplace_offers() -> dict[str, tuple[ParsedOffer, ...]]:
    """Load every offer from the available saved marketplace responses."""
    playerok_response_path = next(
        (path for path in PLAYEROK_RESPONSE_PATHS if path.exists()),
        None,
    )
    ggsel = load_ggsel_payload()
    playerok = (
        load_playerok_payload(playerok_response_path)
        if playerok_response_path is not None
        else LoadedMarketplacePayload(
            marketplace="playerok",
            raw_items=0,
            offers=(),
        )
    )
    funpay = load_funpay_payload()
    return {
        payload.marketplace: payload.offers for payload in (ggsel, playerok, funpay)
    }


def load_ggsel_payload() -> LoadedMarketplacePayload:
    """Extract and normalize the saved GGSEL response with its raw count."""
    from app.parsers.ggsel_extractor import GGSelExtractor
    from app.parsers.normalizers import OfferNormalizer

    if not GGSEL_RESPONSE_PATH.exists():
        return LoadedMarketplacePayload(
            marketplace="ggsel",
            raw_items=0,
            offers=(),
        )
    html = GGSEL_RESPONSE_PATH.read_text(encoding="utf-8")
    raw_offers = GGSelExtractor().extract(html)
    normalizer = OfferNormalizer(marketplace="ggsel")
    return LoadedMarketplacePayload(
        marketplace="ggsel",
        raw_items=len(raw_offers),
        offers=tuple(normalizer.normalize(offer) for offer in raw_offers),
    )


def load_playerok_payload(response_path: Path) -> LoadedMarketplacePayload:
    """Extract and normalize one saved Playerok response with its raw count."""
    from app.parsers.playerok_extractor import PlayerokExtractor
    from app.parsers.playerok_normalizer import PlayerokNormalizer

    raw_response = response_path.read_text(encoding="utf-8")
    extracted = PlayerokExtractor().extract(raw_response)
    return LoadedMarketplacePayload(
        marketplace="playerok",
        raw_items=len(extracted),
        offers=tuple(PlayerokNormalizer().normalize(extracted)),
    )


def load_funpay_payload() -> LoadedMarketplacePayload:
    """Extract and normalize the saved FunPay response with its raw count."""
    from app.parsers.funpay_extractor import FunPayExtractor
    from app.parsers.funpay_normalizer import FunPayNormalizer

    if not FUNPAY_RESPONSE_PATH.exists():
        return LoadedMarketplacePayload(
            marketplace="funpay",
            raw_items=0,
            offers=(),
        )
    raw_response = FUNPAY_RESPONSE_PATH.read_text(encoding="utf-8")
    extracted = FunPayExtractor().extract(raw_response)
    return LoadedMarketplacePayload(
        marketplace="funpay",
        raw_items=len(extracted),
        offers=tuple(FunPayNormalizer().normalize(extracted)),
    )


def snapshot_ready(offers: tuple[ParsedOffer, ...]) -> int:
    """Count offers that contain the fields required by SnapshotBuilder."""
    return sum(
        offer.external_id is not None
        and offer.price is not None
        and offer.currency is not None
        for offer in offers
    )


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")


if __name__ == "__main__":
    main()
