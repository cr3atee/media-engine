from __future__ import annotations

import asyncio
import json
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin


class ScriptCollector(HTMLParser):
    """Collects inline script contents from the GGSEL catalog HTML."""

    def __init__(self) -> None:
        super().__init__()
        self._in_script = False
        self._parts: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "script":
            self._in_script = True
            self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_script:
            content = "".join(self._parts).strip()
            if content:
                self.scripts.append(content)
            self._in_script = False
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self._parts.append(data)


def collect_scripts(raw_html: str) -> list[str]:
    """Return inline script contents from raw HTML."""
    collector = ScriptCollector()
    collector.feed(raw_html)
    collector.close()
    return collector.scripts


def find_push_payload_end(source: str, start: int) -> int | None:
    """Return the closing parenthesis index for a JavaScript push payload."""
    depth = 1
    in_string = False
    escaped = False

    for index in range(start, len(source)):
        char = source[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index

    return None


def extract_json_payloads(script: str) -> list[Any]:
    """Extract JSON payloads pushed into GGSEL frontend state."""
    payloads: list[Any] = []
    marker = ".push("
    start = 0

    while True:
        marker_index = script.find(marker, start)
        if marker_index == -1:
            return payloads

        payload_start = marker_index + len(marker)
        payload_end = find_push_payload_end(script, payload_start)
        if payload_end is None:
            start = payload_start
            continue

        try:
            payloads.append(json.loads(script[payload_start:payload_end]))
        except json.JSONDecodeError:
            pass

        start = payload_end + 1


def looks_like_product(value: dict[str, Any]) -> bool:
    """Return True if a dictionary looks like a GGSEL product payload."""
    return (
        "id_goods" in value
        and "name" in value
        and "url" in value
        and any(key in value for key in ("price_wmr", "price_brl", "price"))
    )


def collect_products(payload: Any, products: list[dict[str, Any]]) -> None:
    """Collect product dictionaries from nested GGSEL frontend payloads."""
    if isinstance(payload, list):
        for item in payload:
            collect_products(item, products)
        return

    if not isinstance(payload, dict):
        return

    if looks_like_product(payload):
        products.append(payload)

    for value in payload.values():
        collect_products(value, products)


def product_price(product: dict[str, Any]) -> str:
    """Return the first available GGSEL product price string."""
    for key in ("price_wmr", "price_brl", "price_wmr_for_one", "price_brl_for_one"):
        value = product.get(key)
        if value is not None:
            return f"{value} RUB"
    value = product.get("price")
    if value is not None:
        return str(value)
    return "unknown"


def product_url(product: dict[str, Any]) -> str:
    """Return an absolute GGSEL product URL."""
    raw_url = product.get("url")
    if not isinstance(raw_url, str):
        return "unknown"
    return urljoin("https://ggsel.net/catalog/", raw_url)


async def main() -> None:
    try:
        from app.core.http_client import HttpClient
        from app.parsers.ggsel_parser import GGSelParser
    except ModuleNotFoundError as exc:
        print(f"Cannot run GGSEL demo: missing module {exc.name!r}.")
        return
    except SyntaxError as exc:
        print(f"Cannot run GGSEL demo with this Python interpreter: {exc}")
        return

    async with HttpClient(timeout=30.0) as http_client:
        parser = GGSelParser(http_client)
        try:
            raw_html = await parser.fetch()
        except RuntimeError as exc:
            print(f"Cannot fetch GGSEL catalog: {exc}")
            return

    products: list[dict[str, Any]] = []
    for script in collect_scripts(raw_html):
        for payload in extract_json_payloads(script):
            collect_products(payload, products)

    unique_products = {str(product.get("id_goods")): product for product in products}
    products = list(unique_products.values())

    if not products:
        print("Cannot extract GGSEL products from the fetched catalog response.")
        print(f"Raw response length: {len(raw_html)} characters.")
        return

    print(f"Products count: {len(products)}")
    for product in products[:5]:
        print()
        print(f"Title: {product.get('name', 'unknown')}")
        print(f"Price: {product_price(product)}")
        print(f"URL: {product_url(product)}")


if __name__ == "__main__":
    asyncio.run(main())
