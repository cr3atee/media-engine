from __future__ import annotations

import json
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, TypeGuard

from app.parsers.models import RawMarketplaceOffer
from app.parsers.source_snapshot import SourceExtraction, SourceSnapshotEvidence


class GGSelExtractor:
    """Extracts typed raw GGSEL products from embedded HTML payloads."""

    _PRICE_FIELDS = (
        ("price_wmr", "RUB"),
        ("price_wmz", "USD"),
        ("price_wme", "EUR"),
        ("price_brl", "BRL"),
    )
    _REQUIRED_FIELDS = frozenset(
        (
            "id_goods",
            "name",
            "url",
            "seller_name",
            "id_section",
        ),
    )

    def extract(self, html: str) -> list[RawMarketplaceOffer]:
        """Return raw product models found in GGSEL embedded JSON payloads."""
        return list(self.extract_with_evidence(html).items)

    def extract_with_evidence(
        self,
        html: str,
    ) -> SourceExtraction[RawMarketplaceOffer]:
        """Extract products and prove whether the embedded page is complete."""
        products: list[RawMarketplaceOffer] = []
        seen_ids: set[str] = set()
        listing_metadata: set[_ListingMetadata] = set()

        for script in _ScriptCollector.collect(html):
            for payload in self._extract_payloads(script):
                self._collect_products(payload, products, seen_ids)
                self._collect_listing_metadata(payload, listing_metadata)

        return SourceExtraction(
            items=tuple(products),
            evidence=self._build_evidence(html, products, listing_metadata),
        )

    def _build_evidence(
        self,
        html: str,
        products: list[RawMarketplaceOffer],
        listing_metadata: set[_ListingMetadata],
    ) -> SourceSnapshotEvidence:
        parsed_ids = frozenset(str(product.id_goods) for product in products)
        parsed_items = len(products)
        if not listing_metadata:
            return SourceSnapshotEvidence(
                source_items=parsed_items,
                parsed_items=parsed_items,
                complete=False,
                reason="GGSEL response has no unambiguous listing total.",
            )

        largest_size = max(len(metadata.item_ids) for metadata in listing_metadata)
        largest = {
            metadata
            for metadata in listing_metadata
            if len(metadata.item_ids) == largest_size
        }
        if len(largest) != 1:
            return SourceSnapshotEvidence(
                source_items=largest_size,
                parsed_items=parsed_items,
                complete=False,
                reason="GGSEL response contains ambiguous listing metadata.",
            )

        metadata = next(iter(largest))
        source_items = len(metadata.item_ids)
        if metadata.item_ids != parsed_ids:
            return SourceSnapshotEvidence(
                source_items=source_items,
                parsed_items=parsed_items,
                expected_items=metadata.total,
                complete=False,
                reason="GGSEL listing identities do not match extracted products.",
            )
        if metadata.total != parsed_items:
            return SourceSnapshotEvidence(
                source_items=source_items,
                parsed_items=parsed_items,
                expected_items=metadata.total,
                complete=False,
                reason=(
                    f"GGSEL embedded {parsed_items} of {metadata.total} "
                    "declared products."
                ),
            )
        if _GGSelMarkupAudit.has_show_more(html):
            return SourceSnapshotEvidence(
                source_items=source_items,
                parsed_items=parsed_items,
                expected_items=metadata.total,
                complete=False,
                reason="GGSEL response exposes a show-more pagination control.",
            )
        return SourceSnapshotEvidence(
            source_items=source_items,
            parsed_items=parsed_items,
            expected_items=metadata.total,
            complete=True,
            reason="GGSEL declared total and extracted product identities match.",
        )

    def _collect_listing_metadata(
        self,
        value: Any,
        metadata: set[_ListingMetadata],
    ) -> None:
        if isinstance(value, list):
            for item in value:
                self._collect_listing_metadata(item, metadata)
            return
        if not isinstance(value, dict):
            return

        items = value.get("items")
        total = self._as_int(value.get("total"))
        if isinstance(items, list) and total is not None:
            item_ids = frozenset(
                str(item_id)
                for item in items
                if self._is_product(item)
                and (item_id := self._as_int(item.get("id_goods"))) is not None
            )
            if item_ids:
                metadata.add(_ListingMetadata(total=total, item_ids=item_ids))

        for item in value.values():
            self._collect_listing_metadata(item, metadata)

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
        products: list[RawMarketplaceOffer],
        seen_ids: set[str],
    ) -> None:
        if isinstance(value, list):
            for item in value:
                self._collect_products(item, products, seen_ids)
            return

        if not isinstance(value, dict):
            return

        if self._is_product(value):
            product = self._build_product(value)
            if product is not None and str(product.id_goods) not in seen_ids:
                products.append(product)
                seen_ids.add(str(product.id_goods))

        for item in value.values():
            self._collect_products(item, products, seen_ids)

    def _is_product(self, value: object) -> TypeGuard[dict[str, object]]:
        return (
            isinstance(value, dict)
            and all(isinstance(key, str) for key in value)
            and self._REQUIRED_FIELDS.issubset(value)
        )

    def _build_product(
        self,
        value: dict[str, object],
    ) -> RawMarketplaceOffer | None:
        id_goods = self._as_int(value.get("id_goods"))
        id_section = self._as_int(value.get("id_section"))
        name = self._as_str(value.get("name"))
        url = self._as_str(value.get("url"))
        seller_name = self._as_str(value.get("seller_name"))
        if (
            id_goods is None
            or id_section is None
            or name is None
            or url is None
            or seller_name is None
        ):
            return None

        known_fields = {
            "id_goods",
            "name",
            "url",
            "seller_name",
            "id_section",
            "image",
            "price",
            "currency",
        }
        extra = {key: item for key, item in value.items() if key not in known_fields}
        price, currency = self._extract_price(value)

        return RawMarketplaceOffer(
            id_goods=id_goods,
            name=name,
            url=url,
            seller_name=seller_name,
            id_section=id_section,
            image=self._as_str(value.get("image")),
            price=price,
            currency=currency,
            extra=extra,
        )

    def _extract_price(
        self,
        value: dict[str, object],
    ) -> tuple[float | None, str | None]:
        price = self._as_float(value.get("price"))
        currency = self._as_str(value.get("currency"))
        if price is not None and currency is not None:
            return price, currency

        for field, field_currency in self._PRICE_FIELDS:
            field_price = self._as_float(value.get(field))
            if field_price is not None:
                return field_price, field_currency

        return price, currency

    def _as_int(self, value: object) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None

    def _as_float(self, value: object) -> float | None:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.replace(",", ".").strip())
            except ValueError:
                return None
        return None

    def _as_str(self, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


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


@dataclass(slots=True, frozen=True)
class _ListingMetadata:
    """GGSEL listing identities and declared source total."""

    total: int
    item_ids: frozenset[str]


class _GGSelMarkupAudit(HTMLParser):
    """Detect explicit client-side pagination controls in GGSEL markup."""

    def __init__(self) -> None:
        super().__init__()
        self.show_more = False

    @classmethod
    def has_show_more(cls, html: str) -> bool:
        """Return whether GGSEL exposes its catalog show-more control."""
        audit = cls()
        audit.feed(html)
        audit.close()
        return audit.show_more

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del tag
        attributes = {name.lower(): value for name, value in attrs}
        data_test = attributes.get("data-test")
        if data_test is not None and data_test.lower() == "showmore":
            self.show_more = True
