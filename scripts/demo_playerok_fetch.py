from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.http_client import HttpClient
from app.parsers.playerok_fetcher import PlayerokFetcher


async def main() -> None:
    """Download one raw Playerok response and print response diagnostics."""
    async with HttpClient(timeout=20.0) as http_client:
        fetcher = PlayerokFetcher(http_client)
        response = await fetcher.fetch()

    content_type = fetcher.last_content_type or "unknown"
    suffix = ".html" if "html" in content_type.lower() else ".txt"
    output_path = Path("tmp") / f"playerok_response{suffix}"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(response, encoding="utf-8")

    print(f"response status: {fetcher.last_status_code}")
    print(f"content type: {content_type}")
    print(f"response size: {len(response.encode('utf-8'))} bytes")
    print("first 500 characters:")
    print(response[:500])
    print(f"saved to: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
