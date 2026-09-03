from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_PATH = PROJECT_ROOT / "tmp" / "funpay_response.html"


async def main() -> None:
    """Download one raw FunPay response and print response diagnostics."""
    from app.core.http_client import HttpClient
    from app.parsers.funpay_fetcher import FunPayFetcher, FunPayFetchError

    async with HttpClient(timeout=30.0) as http_client:
        fetcher = FunPayFetcher(http_client)
        try:
            response = await fetcher.fetch()
        except FunPayFetchError as exc:
            print(f"response status: {fetcher.last_status_code}")
            print(f"diagnostic: {exc}")
            return

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(response, encoding="utf-8")

    print(f"response status: {fetcher.last_status_code}")
    print(f"content type: {fetcher.last_content_type or 'unknown'}")
    print(f"response size: {len(response.encode('utf-8'))} bytes")
    print("first 500 characters:")
    print(response[:500])
    print(f"saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
