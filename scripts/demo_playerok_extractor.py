from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.parsers.playerok_extractor import PlayerokExtractor


def main() -> None:
    """Load a saved Playerok response and print extractor diagnostics."""
    response_path = Path("tmp") / "playerok_response.html"
    if not response_path.exists():
        response_path = Path("tmp") / "playerok_response.txt"

    if not response_path.exists():
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


if __name__ == "__main__":
    main()
