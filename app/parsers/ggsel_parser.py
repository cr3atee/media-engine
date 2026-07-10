from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import httpx

from app.core.http_client import HttpClient
from app.parsers.base import BaseParser
from app.parsers.models import ParsedOffer


class GGSelParser(BaseParser[ParsedOffer]):
    BASE_URL = "https://ggsel.net"
    CATALOG_URL = f"{BASE_URL}/catalog"
    API_URL = f"{BASE_URL}/api"

    def __init__(self, http_client: HttpClient) -> None:
        self._http_client = http_client

    async def fetch(self) -> str:
        try:
            response = await self._http_client.get(self.CATALOG_URL)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            msg = "Failed to fetch GGSEL source response"
            raise RuntimeError(msg) from exc

        return response.text

    async def parse(self, raw_response: str) -> list[ParsedOffer]:
        raw_response = raw_response.strip()
        if not raw_response:
            return []

        try:
            payload = json.loads(raw_response)
        except json.JSONDecodeError:
            return self._parse_html(raw_response)

        return self._parse_json(payload)

    async def run(self) -> Sequence[ParsedOffer]:
        payload = await self.fetch()
        return await self.parse(payload)

    def _parse_json(self, payload: Any) -> list[ParsedOffer]:
        offers: list[ParsedOffer] = []
        for item in self._iter_offer_items(payload):
            offer = self._build_offer(item)
            if offer is not None:
                offers.append(offer)
        return offers

    def _parse_html(self, raw_html: str) -> list[ParsedOffer]:
        scripts = _ScriptCollector.collect(raw_html)
        offers: list[ParsedOffer] = []

        for script in scripts:
            for payload in self._extract_react_query_payloads(script):
                offers.extend(self._parse_json(payload))

        return offers

    def _iter_offer_items(self, payload: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        self._collect_offer_items(payload, items)
        return items

    def _build_offer(self, item: dict[str, Any]) -> ParsedOffer | None:
        external_id = self._first_str(
            item,
            ("external_id", "id_goods", "id", "product_id"),
        )
        title = self._first_str(item, ("title", "name", "product_name"))
        url = self._first_str(item, ("url", "link", "product_url"))
        price = self._first_decimal(
            item,
            (
                "price",
                "price_wmr",
                "price_brl",
                "price_wmr_for_one",
                "price_brl_for_one",
                "cost",
                "amount",
            ),
        )
        currency = self._first_str(item, ("currency", "currency_code")) or "RUB"

        if external_id is None or title is None or url is None or price is None:
            return None

        return ParsedOffer(
            marketplace="ggsel",
            external_id=external_id,
            title=title,
            url=urljoin(f"{self.BASE_URL}/catalog/", url),
            price=price,
            currency=currency,
        )

    def _extract_react_query_payloads(self, script: str) -> list[Any]:
        payloads: list[Any] = []
        marker = ".push("
        start = 0

        while True:
            marker_index = script.find(marker, start)
            if marker_index == -1:
                return payloads

            payload_start = marker_index + len(marker)
            payload_end = self._find_closing_parenthesis(script, payload_start)
            if payload_end is None:
                start = payload_start
                continue

            raw_payload = script[payload_start:payload_end]
            try:
                payloads.append(json.loads(raw_payload))
            except json.JSONDecodeError:
                pass

            start = payload_end + 1

    def _find_closing_parenthesis(self, value: str, start: int) -> int | None:
        depth = 1
        in_string = False
        escaped = False

        for index in range(start, len(value)):
            char = value[index]

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

    def _collect_offer_items(self, payload: Any, items: list[dict[str, Any]]) -> None:
        if isinstance(payload, list):
            for item in payload:
                self._collect_offer_items(item, items)
            return

        if not isinstance(payload, dict):
            return

        if self._looks_like_offer(payload):
            items.append(payload)

        for value in payload.values():
            self._collect_offer_items(value, items)

    def _looks_like_offer(self, item: dict[str, Any]) -> bool:
        return (
            "id_goods" in item
            and "name" in item
            and "url" in item
            and any(key in item for key in ("price_wmr", "price_brl", "price"))
        )

    def _first_str(self, item: dict[str, Any], keys: tuple[str, ...]) -> str | None:
        for key in keys:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, int | float):
                return str(value)
        return None

    def _first_decimal(
        self,
        item: dict[str, Any],
        keys: tuple[str, ...],
    ) -> Decimal | None:
        for key in keys:
            value = item.get(key)
            if value is None:
                continue
            try:
                return Decimal(str(value).replace(",", ".").strip())
            except InvalidOperation:
                continue
        return None


class _ScriptCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_script = False
        self._current_parts: list[str] = []
        self.scripts: list[str] = []

    @classmethod
    def collect(cls, html: str) -> list[str]:
        parser = cls()
        parser.feed(html)
        parser.close()
        return parser.scripts

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "script":
            self._in_script = True
            self._current_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_script:
            script = "".join(self._current_parts).strip()
            if script:
                self.scripts.append(script)
            self._in_script = False
            self._current_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self._current_parts.append(data)
