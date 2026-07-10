from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


async def main() -> None:
    try:
        from app.core.http_client import HttpClient
        from app.parsers.ggsel_parser import GGSelParser
    except ModuleNotFoundError as exc:
        print(f"Cannot run GGSEL parsed offers demo: missing module {exc.name!r}.")
        return
    except SyntaxError as exc:
        print(f"Cannot run GGSEL parsed offers demo with this Python interpreter: {exc}")
        return

    async with HttpClient(timeout=30.0) as http_client:
        parser = GGSelParser(http_client)
        try:
            raw_response = await parser.fetch()
        except RuntimeError as exc:
            print(f"Cannot fetch GGSEL catalog: {exc}")
            return

        offers = await parser.parse(raw_response)

    if not offers:
        print("Cannot extract ParsedOffer objects from the GGSEL catalog response.")
        print(f"Raw response length: {len(raw_response)} characters.")
        return

    unique_offers = {
        f"{offer.marketplace}:{offer.external_id or offer.url or index}": offer
        for index, offer in enumerate(offers)
    }
    offers = list(unique_offers.values())

    print(f"Parsed offers count: {len(offers)}")
    for offer in offers[:10]:
        price = "unknown"
        if offer.price is not None:
            price = str(offer.price)
            if offer.currency is not None:
                price = f"{price} {offer.currency}"

        print()
        print(f"Marketplace: {offer.marketplace}")
        print(f"External ID: {offer.external_id or 'unknown'}")
        print(f"Title: {offer.title or 'unknown'}")
        print(f"Price: {price}")
        print(f"URL: {offer.url or 'unknown'}")
        print(f"Seller ID: {offer.seller_id or 'unknown'}")
        print(f"Seller name: {offer.seller_name or 'unknown'}")


if __name__ == "__main__":
    asyncio.run(main())
