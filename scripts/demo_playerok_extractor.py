from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

RESPONSE_PATHS = (
    PROJECT_ROOT / "tmp" / "playerok_response.json",
    PROJECT_ROOT / "tmp" / "playerok_response.html",
    PROJECT_ROOT / "tmp" / "playerok_response.txt",
)


def main() -> None:
    """Load a saved Playerok response and print extractor diagnostics."""
    _configure_stdout()
    from app.parsers.playerok_extractor import PlayerokExtractor

    response_path = next((path for path in RESPONSE_PATHS if path.exists()), None)
    if response_path is None:
        print("Raw Playerok response is missing.")
        print("Run scripts/demo_playerok_fetch.py first to create fetcher output.")
        return

    raw_response = response_path.read_text(encoding="utf-8")
    offers = PlayerokExtractor().extract(raw_response)

    print(f"number of extracted offers: {len(offers)}")
    if offers:
        print("first ParsedOffer:")
        print(offers[0])
    else:
        print("first ParsedOffer: none")


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")


if __name__ == "__main__":
    main()
