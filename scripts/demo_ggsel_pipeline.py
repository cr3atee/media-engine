from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.http_client import HttpClient
from app.parsers.ggsel_fetcher import GGSelFetcher, GGSelFetchError
from app.parsers.ggsel_parser import GGSelParser
from app.parsers.models import ParsedOffer
from app.parsers.normalizers import OfferNormalizer


async def main() -> None:
    """Fetch real GGSEL raw data and normalize it into ParsedOffer objects."""
    async with HttpClient() as http_client:
        fetcher = GGSelFetcher(http_client)
        normalizer = OfferNormalizer(marketplace="ggsel")

        try:
            raw_offers = await fetcher.fetch(GGSelParser.CATALOG_URL)
        except GGSelFetchError as exc:
            print(f"Response status: {fetcher.last_status_code}")
            print(f"Error: {exc}")
            return

        parsed_offers: list[ParsedOffer] = [
            normalizer.normalize(raw_offer)
            for raw_offer in raw_offers
        ]

        print(f"Parsed offers: {len(parsed_offers)}")
        print()
        for index, offer in enumerate(parsed_offers[:10], start=1):
            print(f"=== ParsedOffer #{index} ===")
            print(f"Title: {offer.title}")
            print(f"Price: {offer.price}")
            print(f"Currency: {offer.currency}")
            print(f"Marketplace: {offer.marketplace}")
            print(f"URL: {offer.url}")
            print()


if __name__ == "__main__":
    asyncio.run(main())
