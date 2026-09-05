from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


async def main() -> None:
    """Run the FunPay pipeline and print extracted offer diagnostics."""
    _configure_stdout()
    from app.core.http_client import HttpClient
    from app.parsers.funpay_extractor import FunPayExtractor
    from app.parsers.funpay_fetcher import FunPayFetcher, FunPayFetchError
    from app.parsers.funpay_normalizer import FunPayNormalizer
    from app.services.funpay_pipeline import FunPayPipeline

    async with HttpClient(timeout=30.0) as http_client:
        pipeline = FunPayPipeline(
            fetcher=FunPayFetcher(http_client),
            extractor=FunPayExtractor(),
            normalizer=FunPayNormalizer(),
        )
        try:
            offers = await pipeline.run()
        except FunPayFetchError as exc:
            print(f"FunPay pipeline failed: {exc}")
            return

    print(f"Parsed offers: {len(offers)}")
    for offer in offers[:10]:
        print()
        print(f"Marketplace: {offer.marketplace}")
        print(f"External ID: {offer.external_id or 'unknown'}")
        print(f"Title: {offer.title or 'unknown'}")
        print(f"Price: {offer.price or 'unknown'} {offer.currency or ''}".strip())
        print(f"URL: {offer.url or 'unknown'}")
        print(f"Seller: {offer.seller_name or 'unknown'}")


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")


if __name__ == "__main__":
    asyncio.run(main())
