from __future__ import annotations

import sys
from pathlib import Path
from pprint import pprint

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.parsers.ggsel_extractor import GGSelExtractor

HTML_PATH = PROJECT_ROOT / "tmp" / "ggsel_response.html"


def main() -> None:
    """Load saved GGSEL HTML and print raw extracted products."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if not HTML_PATH.exists():
        print(f"Missing HTML response: {HTML_PATH}")
        return

    html = HTML_PATH.read_text(encoding="utf-8")
    products = GGSelExtractor().extract(html)

    print(f"Extracted products: {len(products)}")
    print()
    for index, product in enumerate(products[:3], start=1):
        print(f"=== Raw product #{index} ===")
        pprint(product, sort_dicts=False)
        print()


if __name__ == "__main__":
    main()
