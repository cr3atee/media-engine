from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

HTML_PATH = Path("tmp/funpay_response.html")
SNIPPET_RADIUS = 180


@dataclass(slots=True, frozen=True)
class AnchorLink:
    """HTML anchor discovered in the saved FunPay response."""

    href: str
    text: str


class FunPayHtmlCollector(HTMLParser):
    """Collect lightweight HTML clues without extracting marketplace offers."""

    def __init__(self) -> None:
        super().__init__()
        self._current_href: str | None = None
        self._current_text: list[str] = []
        self.links: list[AnchorLink] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attrs_map = dict(attrs)
        href = attrs_map.get("href")
        if href is None:
            return
        self._current_href = href
        self._current_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._current_href is None:
            return
        text = " ".join("".join(self._current_text).split())
        self.links.append(AnchorLink(href=self._current_href, text=text))
        self._current_href = None
        self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._current_text.append(data)


def main() -> None:
    """Analyze a saved FunPay response before product extraction is implemented."""
    if not HTML_PATH.exists():
        print(f"Missing FunPay response: {HTML_PATH}")
        print("Run scripts/demo_funpay_fetch.py or provide a captured response first.")
        return

    html = HTML_PATH.read_text(encoding="utf-8")
    collector = FunPayHtmlCollector()
    collector.feed(html)
    collector.close()

    print("=== RESPONSE ===")
    print(f"Path: {HTML_PATH}")
    print(f"Size: {len(html)} characters")
    print(f"Links: {len(collector.links)}")
    print()

    print("=== STRUCTURE MARKERS ===")
    print_marker_locations(
        html,
        (
            "tc-item",
            "tc-price",
            "tc-desc",
            "media-user-name",
            "data-server",
            "data-side",
            "lot",
            "offer",
            "price",
            "seller",
        ),
    )
    print()

    print("=== POSSIBLE OFFER LINKS ===")
    print_offer_links(collector.links)
    print()

    print("=== PRICE KEYWORD EXAMPLES ===")
    print_keyword_examples(html, ("₽", "руб", "price", "tc-price"))


def print_marker_locations(html: str, markers: tuple[str, ...]) -> None:
    """Print locations for common FunPay marketplace markers."""
    lower_html = html.lower()
    for marker in markers:
        lower_marker = marker.lower()
        positions = [
            match.start() for match in re.finditer(re.escape(lower_marker), lower_html)
        ]
        print(f"{marker}: {len(positions)} occurrence(s)")
        for position in positions[:5]:
            print(f"  at {position}: {snippet(html, position)}")


def print_offer_links(links: list[AnchorLink]) -> None:
    """Print links that may point to lot or offer pages."""
    candidates = [
        link
        for link in links
        if "lots" in link.href.lower() or "orders" in link.href.lower()
    ]
    print(f"Candidate links: {len(candidates)}")
    for link in candidates[:20]:
        title = link.text or "no text"
        print(f"- {title} -> {link.href}")


def print_keyword_examples(html: str, keywords: tuple[str, ...]) -> None:
    """Print nearby HTML snippets for selected keywords."""
    lower_html = html.lower()
    for keyword in keywords:
        lower_keyword = keyword.lower()
        positions = [
            match.start() for match in re.finditer(re.escape(lower_keyword), lower_html)
        ]
        print(f"{keyword}: {len(positions)} occurrence(s)")
        for position in positions[:3]:
            print(f"  at {position}: {snippet(html, position)}")


def snippet(text: str, position: int) -> str:
    """Return a compact one-line snippet around a text position."""
    start = max(0, position - SNIPPET_RADIUS)
    end = min(len(text), position + SNIPPET_RADIUS)
    return " ".join(text[start:end].split())


if __name__ == "__main__":
    main()
