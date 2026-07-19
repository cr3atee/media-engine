from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.parsers.models import ParsedOffer


class OfferNormalizer:
    """Normalizes raw marketplace offer dictionaries into ParsedOffer objects."""

    _EXTERNAL_ID_KEYS = ("external_id", "id", "id_goods")
    _TITLE_KEYS = ("title", "name")
    _PRICE_KEYS = ("price", "amount", "cost")
    _CURRENCY_KEYS = ("currency", "currency_code")
    _URL_KEYS = ("url", "link")
    _SELLER_ID_KEYS = ("seller_id", "id_seller")
    _SELLER_NAME_KEYS = ("seller_name", "name_seller")
    _CURRENCY_ALIASES = {
        "RUR": "RUB",
        "RUB": "RUB",
        "USD": "USD",
        "EUR": "EUR",
    }

    def __init__(self, marketplace: str = "ggsel") -> None:
        """Initialize normalizer with the marketplace assigned to parsed offers."""
        self._marketplace = marketplace

    def normalize(self, raw_offer: dict[str, object]) -> ParsedOffer:
        """Convert a raw marketplace offer dictionary into ParsedOffer."""
        price, currency_from_price = self._normalize_price(
            self._first_value(raw_offer, self._PRICE_KEYS),
        )
        currency = self._normalize_currency(
            self._first_str(raw_offer, self._CURRENCY_KEYS),
        )

        return ParsedOffer(
            marketplace=self._marketplace,
            external_id=self._first_str(raw_offer, self._EXTERNAL_ID_KEYS),
            title=self._clean_text(self._first_str(raw_offer, self._TITLE_KEYS)),
            url=self._clean_text(self._first_str(raw_offer, self._URL_KEYS)),
            price=price,
            currency=currency or currency_from_price,
            seller_id=self._first_str(raw_offer, self._SELLER_ID_KEYS),
            seller_name=self._clean_text(
                self._first_str(raw_offer, self._SELLER_NAME_KEYS),
            ),
        )

    def _first_value(
        self,
        raw_offer: dict[str, object],
        keys: tuple[str, ...],
    ) -> object | None:
        for key in keys:
            value = raw_offer.get(key)
            if value is not None:
                return value
        return None

    def _first_str(
        self,
        raw_offer: dict[str, object],
        keys: tuple[str, ...],
    ) -> str | None:
        value = self._first_value(raw_offer, keys)
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _clean_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        return " ".join(value.split())

    def _normalize_price(
        self,
        value: object | None,
    ) -> tuple[Decimal | None, str | None]:
        if value is None:
            return None, None
        if isinstance(value, Decimal):
            return value, None
        if isinstance(value, int | float):
            return Decimal(str(value)), None

        price: Decimal | None = None
        currency: str | None = None
        for part in str(value).replace(",", ".").split():
            if price is None:
                try:
                    price = Decimal(part)
                    continue
                except InvalidOperation:
                    pass
            currency = currency or self._normalize_currency(part)

        return price, currency

    def _normalize_currency(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        return self._CURRENCY_ALIASES.get(normalized, normalized or None)
