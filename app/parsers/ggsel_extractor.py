from __future__ import annotations

import json
from html.parser import HTMLParser
from typing import Any, TypeGuard


class GGSelExtractor:
    """Extracts raw GGSEL product dictionaries from embedded HTML payloads."""

    _REQUIRED_FIELDS = frozenset(
        (
            "id_goods",
            "name",
            "url",
            "seller_name",
            "id_section",
        ),
    )

    def extract(self, html: str) -> list[dict[str, object]]:
        """Return raw product objects found in GGSEL embedded JSON payloads."""
        products: list[dict[str, object]] = []
        seen_ids: set[str] = set()

        for script in _ScriptCollector.collect(html):
            for payload in self._extract_payloads(script):
                self._collect_products(payload, products, seen_ids)

        return products

    def _extract_payloads(self, script: str) -> list[Any]:
        payloads: list[Any] = []
        stripped = script.strip()
        if stripped.startswith(("{", "[")):
            self._append_json_payload(stripped, payloads)

        marker = ".push("
        start = 0
        while True:
            marker_index = script.find(marker, start)
            if marker_index == -1:
                return payloads

            payload_start = marker_index + len(marker)
            payload_end = self._find_payload_end(script, payload_start)
            if payload_end is None:
                start = payload_start
                continue

            self._append_json_payload(script[payload_start:payload_end], payloads)
            start = payload_end + 1

    def _append_json_payload(self, raw_payload: str, payloads: list[Any]) -> None:
        try:
            payloads.append(json.loads(raw_payload))
        except json.JSONDecodeError:
            return

    def _find_payload_end(self, source: str, start: int) -> int | None:
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

    def _collect_products(
        self,
        value: Any,
        products: list[dict[str, object]],
        seen_ids: set[str],
    ) -> None:
        if isinstance(value, list):
            for item in value:
                self._collect_products(item, products, seen_ids)
            return

        if not isinstance(value, dict):
            return

        if self._is_product(value):
            product = dict(value)
            product_id = str(product["id_goods"])
            if product_id not in seen_ids:
                products.append(product)
                seen_ids.add(product_id)

        for item in value.values():
            self._collect_products(item, products, seen_ids)

    def _is_product(self, value: object) -> TypeGuard[dict[str, object]]:
        return isinstance(value, dict) and self._REQUIRED_FIELDS.issubset(value)


class _ScriptCollector(HTMLParser):
    """Collects script contents from HTML without interpreting markup."""

    def __init__(self) -> None:
        super().__init__()
        self._in_script = False
        self._parts: list[str] = []
        self.scripts: list[str] = []

    @classmethod
    def collect(cls, html: str) -> list[str]:
        """Return all script contents from an HTML document."""
        collector = cls()
        collector.feed(html)
        collector.close()
        return collector.scripts

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "script":
            self._in_script = True
            self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_script:
            script = "".join(self._parts).strip()
            if script:
                self.scripts.append(script)
            self._in_script = False
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self._parts.append(data)
