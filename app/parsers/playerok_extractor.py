from __future__ import annotations

import json
import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any

from app.parsers.models import ParsedOffer

type JsonObject = dict[str, Any]


class PlayerokExtractor:
    """Extracts Playerok marketplace offers from a raw response body."""

    MARKETPLACE = "playerok"
    PRODUCT_URL_PREFIX = "https://playerok.com/products/"

    def extract(self, raw_response: str) -> list[ParsedOffer]:
        """Return ParsedOffer objects found in a raw Playerok response."""
        payload = self._load_payload(raw_response)
        if payload is None:
            return []

        return [
            self._to_parsed_offer(item)
            for item in self._iter_objects(payload)
            if self._looks_like_offer(item)
        ]

    def _load_payload(self, raw_response: str) -> Any | None:
        try:
            return json.loads(raw_response)
        except json.JSONDecodeError:
            return self._load_next_data(raw_response)

    def _load_next_data(self, raw_response: str) -> Any | None:
        match = re.search(
            r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
            raw_response,
            flags=re.DOTALL,
        )
        if match is None:
            return None

        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

    def _iter_objects(self, payload: Any) -> Iterable[JsonObject]:
        if isinstance(payload, dict):
            yield payload
            for value in payload.values():
                yield from self._iter_objects(value)
        elif isinstance(payload, list):
            for value in payload:
                yield from self._iter_objects(value)

    def _looks_like_offer(self, item: JsonObject) -> bool:
        has_identifier = any(key in item for key in ("id", "slug"))
        has_offer_data = any(key in item for key in ("name", "title", "price", "url"))
        return has_identifier and has_offer_data

    def _to_parsed_offer(self, item: JsonObject) -> ParsedOffer:
        slug = self._as_str(item.get("slug"))
        return ParsedOffer(
            marketplace=self.MARKETPLACE,
            external_id=self._external_id(item, slug),
            title=self._title(item),
            url=self._url(item, slug),
            price=self._price(item),
            currency=self._currency(item),
            seller_id=self._seller_id(item),
            seller_name=self._seller_name(item),
            canonical_product_id=None,
        )

    def _external_id(self, item: JsonObject, slug: str | None) -> str | None:
        return self._as_str(item.get("id")) or slug

    def _title(self, item: JsonObject) -> str | None:
        title = self._as_str(item.get("name")) or self._as_str(item.get("title"))
        return title.strip() if title is not None else None

    def _url(self, item: JsonObject, slug: str | None) -> str | None:
        url = self._as_str(item.get("url"))
        if url is not None and url.startswith(("http://", "https://")):
            return url
        if slug is not None:
            return f"{self.PRODUCT_URL_PREFIX}{slug}"
        return None

    def _price(self, item: JsonObject) -> Decimal | None:
        value = item.get("price")
        if isinstance(value, dict):
            value = value.get("amount") or value.get("value")

        if isinstance(value, int | float | Decimal | str):
            try:
                return Decimal(str(value).strip())
            except InvalidOperation:
                return None

        return None

    def _currency(self, item: JsonObject) -> str | None:
        value = item.get("currency")
        if value is None and isinstance(item.get("price"), dict):
            value = item["price"].get("currency")

        currency = self._as_str(value)
        return currency.upper() if currency is not None else None

    def _seller_id(self, item: JsonObject) -> str | None:
        seller = self._nested_object(item, "seller", "user", "owner")
        if seller is None:
            return None
        return self._as_str(seller.get("id"))

    def _seller_name(self, item: JsonObject) -> str | None:
        seller = self._nested_object(item, "seller", "user", "owner")
        if seller is None:
            return None

        name = (
            self._as_str(seller.get("username"))
            or self._as_str(seller.get("name"))
        )
        return name.strip() if name is not None else None

    def _nested_object(self, item: JsonObject, *keys: str) -> JsonObject | None:
        for key in keys:
            value = item.get(key)
            if isinstance(value, dict):
                return value
        return None

    def _as_str(self, value: object) -> str | None:
        if isinstance(value, str):
            return value
        if isinstance(value, int):
            return str(value)
        return None
