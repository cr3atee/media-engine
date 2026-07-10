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
        if not raw_response.strip():
            return []

        offers: list[ParsedOffer] = []
        for script in _ScriptCollector.collect(raw_response):
            for payload in self._extract_json_payloads(script):
                self._collect_offers(payload, offers)
        return offers

    async def run(self) -> Sequence[ParsedOffer]:
        payload = await self.fetch()
        return await self.parse(payload)

    def _extract_json_payloads(self, script: str) -> list[Any]:
        payloads: list[Any] = []
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

            try:
                payloads.append(json.loads(script[payload_start:payload_end]))
            except json.JSONDecodeError:
                pass

            start = payload_end + 1

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

    def _collect_offers(self, payload: Any, offers: list[ParsedOffer]) -> None:
        if isinstance(payload, list):
            for item in payload:
                self._collect_offers(item, offers)
            return

        if not isinstance(payload, dict):
            return

        if self._looks_like_offer(payload):
            offers.append(self._build_offer(payload))

        for value in payload.values():
            self._collect_offers(value, offers)

    def _looks_like_offer(self, payload: dict[str, Any]) -> bool:
        return (
            any(key in payload for key in ("id_goods", "external_id", "id"))
            or ("name" in payload and "url" in payload)
            or ("title" in payload and "url" in payload)
        )

    def _build_offer(self, payload: dict[str, Any]) -> ParsedOffer:
        external_id = self._first_str(payload, ("id_goods", "external_id", "id"))
        title = self._first_str(payload, ("name", "title"))
        raw_url = self._first_str(payload, ("url", "link"))
        price = self._first_decimal(
            payload,
            (
                "price_wmr",
                "price_brl",
                "price_wmr_for_one",
                "price_brl_for_one",
                "price",
            ),
        )
        url = None
        if raw_url is not None:
            url = urljoin(f"{self.BASE_URL}/catalog/", raw_url)

        return ParsedOffer(
            marketplace="ggsel",
            external_id=external_id,
            title=title,
            url=url,
            price=price,
            currency=self._first_str(payload, ("currency", "currency_code")),
            seller_id=self._first_str(payload, ("id_seller", "seller_id")),
            seller_name=self._first_str(payload, ("name_seller", "seller_name")),
        )

    def _first_str(self, payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, int | float):
                return str(value)
        return None

    def _first_decimal(
        self,
        payload: dict[str, Any],
        keys: tuple[str, ...],
    ) -> Decimal | None:
        for key in keys:
            value = payload.get(key)
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
        self._parts: list[str] = []
        self.scripts: list[str] = []

    @classmethod
    def collect(cls, raw_html: str) -> list[str]:
        collector = cls()
        collector.feed(raw_html)
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
