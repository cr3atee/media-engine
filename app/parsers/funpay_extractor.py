from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlparse

from app.parsers.models import ParsedOffer

_BASE_URL = "https://funpay.com/"
_PRICE_RE = re.compile(
    r"(?P<amount>\d+(?:[\s\u00a0]\d{3})*(?:[,.]\d+)?)\s*"
    r"(?P<currency>₽|руб\.?|rub|usd|\$|eur|€)",
    flags=re.IGNORECASE,
)
_CURRENCY_ALIASES = {
    "₽": "RUB",
    "руб": "RUB",
    "руб.": "RUB",
    "rub": "RUB",
    "$": "USD",
    "usd": "USD",
    "€": "EUR",
    "eur": "EUR",
}


@dataclass(slots=True)
class _OfferCandidate:
    href: str
    text_parts: list[str] = field(default_factory=list)
    title_parts: list[str] = field(default_factory=list)
    seller_parts: list[str] = field(default_factory=list)
    price_parts: list[str] = field(default_factory=list)


class FunPayExtractor:
    """Extracts FunPay marketplace offers from public listing HTML."""

    MARKETPLACE = "funpay"

    def extract(self, raw_response: str) -> list[ParsedOffer]:
        """Return ParsedOffer objects found in a raw FunPay listing response."""
        parser = _FunPayOfferHtmlParser()
        parser.feed(raw_response)
        parser.close()

        offers: list[ParsedOffer] = []
        seen_ids: set[str] = set()
        for candidate in parser.candidates:
            offer = self._to_parsed_offer(candidate)
            if offer is None or offer.external_id in seen_ids:
                continue
            offers.append(offer)
            if offer.external_id is not None:
                seen_ids.add(offer.external_id)
        return offers

    def _to_parsed_offer(self, candidate: _OfferCandidate) -> ParsedOffer | None:
        external_id = self._external_id(candidate.href)
        if external_id is None:
            return None

        price_text = " ".join(candidate.price_parts or candidate.text_parts)
        price, currency = self._price(price_text)
        title = self._title(candidate, price_text)
        seller_name = self._clean_text(" ".join(candidate.seller_parts))

        return ParsedOffer(
            marketplace=self.MARKETPLACE,
            external_id=external_id,
            title=title,
            url=urljoin(_BASE_URL, candidate.href),
            price=price,
            currency=currency,
            seller_name=seller_name,
        )

    def _external_id(self, href: str) -> str | None:
        query = parse_qs(urlparse(href).query)
        values = query.get("id")
        if not values:
            return None
        value = values[0].strip()
        return value or None

    def _price(self, text: str) -> tuple[Decimal | None, str | None]:
        match = _PRICE_RE.search(text)
        if match is None:
            return None, None

        amount = match.group("amount").replace(" ", "").replace("\u00a0", "")
        currency = _CURRENCY_ALIASES.get(match.group("currency").lower())
        try:
            return Decimal(amount.replace(",", ".")), currency
        except InvalidOperation:
            return None, currency

    def _title(self, candidate: _OfferCandidate, price_text: str) -> str | None:
        title = self._clean_text(" ".join(candidate.title_parts))
        if title is not None:
            return title

        text = self._clean_text(" ".join(candidate.text_parts))
        if text is None:
            return None
        match = _PRICE_RE.search(price_text)
        if match is None:
            return text
        return self._clean_text(text.replace(match.group(0), ""))

    def _clean_text(self, value: str) -> str | None:
        text = " ".join(value.split())
        return text or None


class _FunPayOfferHtmlParser(HTMLParser):
    """Collect raw FunPay offer anchors without domain decisions."""

    def __init__(self) -> None:
        super().__init__()
        self._candidate: _OfferCandidate | None = None
        self._anchor_depth = 0
        self._class_stack: list[set[str]] = []
        self.candidates: list[_OfferCandidate] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        classes = _classes(attrs_map.get("class"))

        if self._candidate is not None:
            self._anchor_depth += 1
            self._class_stack.append(classes)
            return

        href = attrs_map.get("href")
        if tag.lower() == "a" and href is not None and _is_offer_href(href):
            self._candidate = _OfferCandidate(href=href)
            self._anchor_depth = 1
            self._class_stack = [classes]

    def handle_endtag(self, tag: str) -> None:
        if self._candidate is None:
            return

        self._anchor_depth -= 1
        if self._class_stack:
            self._class_stack.pop()

        if self._anchor_depth <= 0:
            self.candidates.append(self._candidate)
            self._candidate = None
            self._anchor_depth = 0
            self._class_stack = []

    def handle_data(self, data: str) -> None:
        if self._candidate is None:
            return

        text = " ".join(data.split())
        if not text:
            return

        active_classes = set().union(*self._class_stack) if self._class_stack else set()
        self._candidate.text_parts.append(text)

        if "tc-desc-text" in active_classes or "tc-desc" in active_classes:
            self._candidate.title_parts.append(text)
        elif "media-user-name" in active_classes:
            self._candidate.seller_parts.append(text)
        elif "tc-price" in active_classes:
            self._candidate.price_parts.append(text)


def _is_offer_href(href: str) -> bool:
    parsed = urlparse(href)
    return parsed.path.endswith("/lots/offer") and "id" in parse_qs(parsed.query)


def _classes(value: str | None) -> set[str]:
    if value is None:
        return set()
    return set(value.split())
