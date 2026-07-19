from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

HTML_PATH = Path("tmp/ggsel_response.html")
SNIPPET_RADIUS = 180


@dataclass(slots=True, frozen=True)
class ScriptBlock:
    """HTML script block discovered in the saved GGSEL response."""

    index: int
    attrs: dict[str, str | None]
    content: str


class ScriptCollector(HTMLParser):
    """Collect script blocks without interpreting product data."""

    def __init__(self) -> None:
        super().__init__()
        self._in_script = False
        self._attrs: dict[str, str | None] = {}
        self._parts: list[str] = []
        self.scripts: list[ScriptBlock] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "script":
            self._in_script = True
            self._attrs = dict(attrs)
            self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_script:
            self.scripts.append(
                ScriptBlock(
                    index=len(self.scripts),
                    attrs=self._attrs,
                    content="".join(self._parts).strip(),
                ),
            )
            self._in_script = False
            self._attrs = {}
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self._parts.append(data)


def main() -> None:
    """Analyze the saved GGSEL HTML response for embedded data locations."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if not HTML_PATH.exists():
        print(f"Missing HTML response: {HTML_PATH}")
        return

    html = HTML_PATH.read_text(encoding="utf-8")
    collector = ScriptCollector()
    collector.feed(html)
    collector.close()

    print("=== RESPONSE ===")
    print(f"Path: {HTML_PATH}")
    print(f"Size: {len(html)} characters")
    print(f"Script blocks: {len(collector.scripts)}")
    print()

    print("=== DETECTED FRAMEWORK ===")
    print(detect_framework(html))
    print()

    print("=== EMBEDDED DATA LOCATIONS ===")
    print_marker_locations(html, ("__NEXT_DATA__", "INITIAL_STATE", "self.__next_f"))
    print_json_script_blocks(collector.scripts)
    print()

    print("=== PRODUCT KEYWORD EXAMPLES ===")
    print_keyword_examples(
        html,
        (
            "product",
            "products",
            "goods",
            "id_goods",
            "offer",
            "title",
            "name",
            "товар",
        ),
    )
    print()

    print("=== PRICE KEYWORD EXAMPLES ===")
    print_keyword_examples(
        html,
        (
            "price",
            "price_wmr",
            "price_brl",
            "currency",
            "₽",
            "руб",
        ),
    )
    print()

    print("=== PRODUCT IDENTIFIER EXAMPLES ===")
    print_keyword_examples(
        html,
        (
            "id_goods",
            "external_id",
            "product_id",
            "seller_id",
            "id_seller",
        ),
    )
    print()

    print("=== POSSIBLE PRODUCT DATA STRUCTURE ===")
    print_possible_structure(collector.scripts)


def detect_framework(html: str) -> str:
    """Return a best-effort framework hint from common response markers."""
    if "__NEXT_DATA__" in html or "_next/static" in html or "self.__next_f" in html:
        return "Next.js / React Server Components markers detected."
    if "INITIAL_STATE" in html:
        return "Client-side initial state marker detected."
    return "No common framework marker detected."


def print_marker_locations(html: str, markers: tuple[str, ...]) -> None:
    """Print locations for common embedded data markers."""
    for marker in markers:
        positions = [match.start() for match in re.finditer(re.escape(marker), html)]
        print(f"{marker}: {len(positions)} occurrence(s)")
        for position in positions[:5]:
            print(f"  at {position}: {snippet(html, position)}")


def print_json_script_blocks(scripts: list[ScriptBlock]) -> None:
    """Print script blocks that look like JSON or embedded data containers."""
    candidates = [
        script
        for script in scripts
        if looks_like_json_script(script) or "self.__next_f.push(" in script.content
    ]
    print(f"JSON-like script blocks: {len(candidates)}")
    for script in candidates[:10]:
        script_type = script.attrs.get("type")
        script_id = script.attrs.get("id")
        print(
            f"  script #{script.index}: type={script_type!r}, "
            f"id={script_id!r}, size={len(script.content)}"
        )
        print(f"    {snippet(script.content, 0)}")


def looks_like_json_script(script: ScriptBlock) -> bool:
    """Return whether a script block appears to contain JSON data."""
    script_type = script.attrs.get("type")
    content = script.content.lstrip()
    return (
        script_type == "application/json"
        or script_type == "application/ld+json"
        or content.startswith("{")
        or content.startswith("[")
    )


def print_keyword_examples(html: str, keywords: tuple[str, ...]) -> None:
    """Print nearby HTML snippets for selected keywords."""
    lower_html = html.lower()
    for keyword in keywords:
        lower_keyword = keyword.lower()
        positions = [
            match.start()
            for match in re.finditer(re.escape(lower_keyword), lower_html)
        ]
        print(f"{keyword}: {len(positions)} occurrence(s)")
        for position in positions[:3]:
            print(f"  at {position}: {snippet(html, position)}")


def print_possible_structure(scripts: list[ScriptBlock]) -> None:
    """Print structural clues without extracting concrete products."""
    push_scripts = [
        script for script in scripts if "self.__next_f.push(" in script.content
    ]
    if push_scripts:
        print("React Server Components stream scripts are present.")
        print("Potential data may be serialized inside self.__next_f.push(...) calls.")
        for script in push_scripts[:5]:
            keys = find_key_examples(script.content)
            print(f"  script #{script.index} possible keys: {', '.join(keys) or 'none'}")
        return

    json_scripts = [script for script in scripts if looks_like_json_script(script)]
    if json_scripts:
        print("JSON-like script blocks are present.")
        for script in json_scripts[:5]:
            keys = find_key_examples(script.content)
            print(f"  script #{script.index} possible keys: {', '.join(keys) or 'none'}")
        return

    print("No obvious embedded product data structure detected.")


def find_key_examples(text: str) -> list[str]:
    """Return likely JSON key names found in a text sample."""
    keys = re.findall(r'"([A-Za-z_][A-Za-z0-9_]{1,40})"\s*:', text)
    seen: list[str] = []
    for key in keys:
        if key not in seen:
            seen.append(key)
        if len(seen) == 12:
            break
    return seen


def snippet(text: str, position: int) -> str:
    """Return a compact one-line snippet around a text position."""
    start = max(0, position - SNIPPET_RADIUS)
    end = min(len(text), position + SNIPPET_RADIUS)
    return " ".join(text[start:end].split())


if __name__ == "__main__":
    main()
