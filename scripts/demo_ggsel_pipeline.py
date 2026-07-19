from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.http_client import HttpClient
from app.parsers.ggsel_parser import GGSelParser

HTML_RESPONSE_PATH = PROJECT_ROOT / "tmp" / "ggsel_response.html"


async def main() -> None:
    """Fetch the GGSEL catalog response and print HTML diagnostics."""
    async with HttpClient() as http_client:
        response = await http_client.get(GGSelParser.CATALOG_URL)

    content_type = response.headers.get("content-type", "")
    body = response.text

    print(f"Response status: {response.status_code}")
    print(f"Detected content type: {content_type}")
    print(f"Response size: {len(response.content)} bytes")
    print("First 500 characters:")
    print(body[:500])

    if "html" in content_type.lower():
        HTML_RESPONSE_PATH.parent.mkdir(parents=True, exist_ok=True)
        HTML_RESPONSE_PATH.write_text(body, encoding="utf-8")
        print(f"HTML response saved to: {HTML_RESPONSE_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
