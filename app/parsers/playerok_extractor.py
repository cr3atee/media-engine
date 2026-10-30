from __future__ import annotations

import json
import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any

from app.parsers.models import ParsedOffer
from app.parsers.source_snapshot import SourceExtraction, SourceSnapshotEvidence

type JsonObject = dict[str, Any]


class PlayerokExtractor:
    """Extracts Playerok marketplace offers from a raw response body."""

    MARKETPLACE = "playerok"
    PRODUCT_URL_PREFIX = "https://playerok.com/products/"

    def extract(self, raw_response: str) -> list[ParsedOffer]:
        """Return ParsedOffer objects found in a raw Playerok response."""
        return list(self.extract_with_evidence(raw_response).items)

    def extract_with_evidence(
        self,
        raw_response: str,
    ) -> SourceExtraction[ParsedOffer]:
        """Extract offers and prove complete GraphQL cursor coverage."""
        payload = self._load_payload(raw_response)
        if payload is None:
            return self._result(
                (),
                source_items=0,
                complete=False,
                reason="Playerok response is not a supported structured payload.",
            )

        graphql_listing = self._graphql_listing(payload)
        if graphql_listing is None:
            unverified_offers = tuple(
                self._to_parsed_offer(item)
                for item in self._iter_objects(payload)
                if self._looks_like_offer(item)
            )
            return self._result(
                unverified_offers,
                source_items=len(unverified_offers),
                complete=False,
                reason="Playerok response has no authoritative GraphQL listing total.",
            )

        edges, expected_items, has_next_page = graphql_listing
        offers: list[ParsedOffer] = []
        offer_ids: list[str] = []
        for edge in edges:
            node = edge.get("node") if isinstance(edge, dict) else None
            if not isinstance(node, dict) or not self._looks_like_offer(node):
                continue
            offer = self._to_parsed_offer(node)
            offers.append(offer)
            if offer.external_id is not None:
                offer_ids.append(offer.external_id)

        identities_complete = len(offer_ids) == len(edges)
        identities_unique = len(set(offer_ids)) == len(offer_ids)
        parser_coverage = len(offers) == len(edges)
        total_matches = expected_items is not None and expected_items == len(edges)
        final_page = has_next_page is False
        complete = (
            final_page
            and parser_coverage
            and identities_complete
            and identities_unique
            and total_matches
        )
        if expected_items is None:
            reason = "Playerok GraphQL listing has no valid declared total."
        elif not final_page:
            reason = "Playerok GraphQL listing has additional cursor pages."
        elif not parser_coverage or not identities_complete:
            reason = "Playerok GraphQL edges were not fully extracted."
        elif not identities_unique:
            reason = "Playerok GraphQL listing contains duplicate product identities."
        elif not total_matches:
            reason = (
                f"Playerok returned {len(edges)} of {expected_items} declared items."
            )
        else:
            reason = (
                "Playerok final cursor page, declared total, and extracted "
                "product identities match."
            )

        return self._result(
            tuple(offers),
            source_items=len(edges),
            expected_items=expected_items,
            complete=complete,
            reason=reason,
        )

    def _result(
        self,
        offers: tuple[ParsedOffer, ...],
        *,
        source_items: int,
        complete: bool,
        reason: str,
        expected_items: int | None = None,
    ) -> SourceExtraction[ParsedOffer]:
        return SourceExtraction(
            items=offers,
            evidence=SourceSnapshotEvidence(
                source_items=source_items,
                parsed_items=len(offers),
                expected_items=expected_items,
                complete=complete,
                reason=reason,
            ),
        )

    def _graphql_listing(
        self,
        payload: Any,
    ) -> tuple[list[Any], int | None, bool | None] | None:
        if not isinstance(payload, dict):
            return None
        data = payload.get("data")
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, dict):
            return None
        edges = items.get("edges")
        if not isinstance(edges, list):
            return None
        raw_total = items.get("totalCount")
        expected_items = (
            raw_total
            if isinstance(raw_total, int) and not isinstance(raw_total, bool)
            else None
        )
        page_info = items.get("pageInfo")
        raw_has_next = (
            page_info.get("hasNextPage") if isinstance(page_info, dict) else None
        )
        has_next_page = raw_has_next if isinstance(raw_has_next, bool) else None
        return edges, expected_items, has_next_page

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
        has_title = any(key in item for key in ("name", "title"))
        has_price = any(key in item for key in ("price", "rawPrice"))
        return has_identifier and has_title and has_price

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
            source_category_id=self._source_category_id(item),
            source_category_name=self._source_category_name(item),
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

        name = self._as_str(seller.get("username")) or self._as_str(seller.get("name"))
        return name.strip() if name is not None else None

    def _source_category_id(self, item: JsonObject) -> str | None:
        category = self._nested_object(item, "category")
        return self._as_str(category.get("id")) if category is not None else None

    def _source_category_name(self, item: JsonObject) -> str | None:
        category = self._nested_object(item, "category")
        if category is None:
            return None
        name = self._as_str(category.get("name"))
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
