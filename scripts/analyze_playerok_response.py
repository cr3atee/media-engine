from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

RESPONSE_PATHS = (
    Path("tmp/playerok_response.html"),
    Path("tmp/playerok_response.json"),
    Path("tmp/playerok_response.txt"),
)
SNIPPET_RADIUS = 180


@dataclass(slots=True, frozen=True)
class ScriptBlock:
    """HTML script block discovered in the saved Playerok response."""

    index: int
    attrs: dict[str, str | None]
    content: str


class ScriptCollector(HTMLParser):
    """Collect script blocks without extracting marketplace offers."""

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
    """Analyze a saved Playerok response for structured data locations."""
    response_path = _first_existing_response()
    if response_path is None:
        print("Missing Playerok response.")
        print(
            "Run scripts/demo_playerok_fetch.py or provide a captured response first."
        )
        return

    response = response_path.read_text(encoding="utf-8")
    collector = ScriptCollector()
    collector.feed(response)
    collector.close()

    print("=== RESPONSE ===")
    print(f"Path: {response_path}")
    print(f"Size: {len(response)} characters")
    print(f"Script blocks: {len(collector.scripts)}")
    print()

    print("=== DETECTED FRAMEWORK ===")
    print(detect_framework(response))
    print()

    print("=== EMBEDDED DATA LOCATIONS ===")
    print_marker_locations(
        response,
        (
            "__NEXT_DATA__",
            "dehydratedState",
            "apolloState",
            "Apollo",
            "graphql",
            "/graphql",
            "rest-api/public",
            "products",
            "page_info",
        ),
    )
    print_json_script_blocks(collector.scripts)
    print()

    print("=== PRODUCT KEYWORD EXAMPLES ===")
    print_keyword_examples(
        response,
        (
            "product",
            "products",
            "item",
            "items",
            "slug",
            "name",
            "title",
            "seller",
        ),
    )
    print()

    print("=== PRICE KEYWORD EXAMPLES ===")
    print_keyword_examples(
        response,
        (
            "price",
            "raw_price",
            "currency",
            "amount",
            "value",
        ),
    )
    print()

    print("=== POSSIBLE STRUCTURE ===")
    print_possible_structure(response, collector.scripts)


def _first_existing_response() -> Path | None:
    for path in RESPONSE_PATHS:
        if path.exists():
            return path
    return None


def detect_framework(response: str) -> str:
    """Return a best-effort framework hint from common response markers."""
    if "__NEXT_DATA__" in response or "_next/static" in response:
        return "Next.js markers detected."
    if "apolloState" in response or "graphql" in response.lower():
        return "Apollo/GraphQL markers detected."
    if response.lstrip().startswith(("{", "[")):
        return "Raw JSON response detected."
    return "No common framework marker detected."


def print_marker_locations(response: str, markers: tuple[str, ...]) -> None:
    """Print locations for common embedded data markers."""
    lower_response = response.lower()
    for marker in markers:
        lower_marker = marker.lower()
        positions = [
            match.start()
            for match in re.finditer(re.escape(lower_marker), lower_response)
        ]
        print(f"{marker}: {len(positions)} occurrence(s)")
        for position in positions[:5]:
            print(f"  at {position}: {snippet(response, position)}")


def print_json_script_blocks(scripts: list[ScriptBlock]) -> None:
    """Print script blocks that appear to contain JSON-like data."""
    candidates = [script for script in scripts if looks_like_json_script(script)]
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


def print_keyword_examples(response: str, keywords: tuple[str, ...]) -> None:
    """Print nearby response snippets for selected keywords."""
    lower_response = response.lower()
    for keyword in keywords:
        lower_keyword = keyword.lower()
        positions = [
            match.start()
            for match in re.finditer(re.escape(lower_keyword), lower_response)
        ]
        print(f"{keyword}: {len(positions)} occurrence(s)")
        for position in positions[:3]:
            print(f"  at {position}: {snippet(response, position)}")


def print_possible_structure(response: str, scripts: list[ScriptBlock]) -> None:
    """Print structural clues without converting data into ParsedOffer."""
    json_payload = parse_json_if_possible(response)
    if json_payload is not None:
        print("Top-level JSON payload detected.")
        print(f"Top-level keys: {', '.join(top_level_keys(json_payload)) or 'none'}")
        return

    next_data = next(
        (script for script in scripts if script.attrs.get("id") == "__NEXT_DATA__"),
        None,
    )
    if next_data is not None:
        payload = parse_json_if_possible(next_data.content)
        print("__NEXT_DATA__ script detected.")
        if payload is not None:
            print(f"Top-level keys: {', '.join(top_level_keys(payload)) or 'none'}")
            print(f"Likely keys: {', '.join(find_key_examples(next_data.content))}")
        return

    json_scripts = [script for script in scripts if looks_like_json_script(script)]
    if json_scripts:
        print("JSON-like script blocks are present.")
        for script in json_scripts[:5]:
            keys = find_key_examples(script.content)
            print(
                f"  script #{script.index} possible keys: {', '.join(keys) or 'none'}"
            )
        return

    print("No obvious embedded product data structure detected.")


def parse_json_if_possible(value: str) -> Any | None:
    """Return parsed JSON data when the value is valid JSON."""
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def top_level_keys(payload: Any) -> list[str]:
    """Return top-level keys for dictionary payloads."""
    if not isinstance(payload, dict):
        return []
    return [str(key) for key in payload][:20]


def find_key_examples(text: str) -> list[str]:
    """Return likely JSON key names found in a text sample."""
    keys = re.findall(r'"([A-Za-z_][A-Za-z0-9_]{1,40})"\s*:', text)
    unique: list[str] = []
    for key in keys:
        if key not in unique:
            unique.append(key)
        if len(unique) >= 20:
            break
    return unique


def snippet(text: str, position: int) -> str:
    """Return a compact one-line snippet around a text position."""
    start = max(0, position - SNIPPET_RADIUS)
    end = min(len(text), position + SNIPPET_RADIUS)
    return " ".join(text[start:end].split())


if __name__ == "__main__":
    main()
