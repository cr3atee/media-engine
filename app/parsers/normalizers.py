from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.parsers.models import ParsedOffer, RawMarketplaceOffer


class OfferNormalizer:
    """Normalizes typed raw marketplace offers into ParsedOffer objects."""

    _SELLER_ID_KEYS = ("seller_id", "id_seller")
    _CURRENCY_ALIASES = {
        "RUR": "RUB",
        "RUB": "RUB",
        "USD": "USD",
        "EUR": "EUR",
    }

    def __init__(self, marketplace: str = "ggsel") -> None:
        """Initialize normalizer with the marketplace assigned to parsed offers."""
        self._marketplace = marketplace

    def normalize(self, raw_offer: RawMarketplaceOffer) -> ParsedOffer:
        """Convert a typed raw marketplace offer into ParsedOffer."""
        price, currency_from_price = self._normalize_price(raw_offer.price)
        currency = self._normalize_currency(raw_offer.currency)

        return ParsedOffer(
            marketplace=self._marketplace,
            external_id=str(raw_offer.id_goods),
            title=self._clean_text(raw_offer.name),
            url=self._clean_text(raw_offer.url),
            price=price,
            currency=currency or currency_from_price,
            seller_id=self._first_extra_str(raw_offer, self._SELLER_ID_KEYS),
            seller_name=self._clean_text(raw_offer.seller_name),
        )

    def _first_extra_str(
        self,
        raw_offer: RawMarketplaceOffer,
        keys: tuple[str, ...],
    ) -> str | None:
        for key in keys:
            value = raw_offer.extra.get(key)
            if value is not None:
                text = str(value).strip()
                return text or None
        return None

    def _clean_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        return " ".join(value.split())

    def _normalize_price(
        self,
        value: float | None,
    ) -> tuple[Decimal | None, str | None]:
        if value is None:
            return None, None
        try:
            return Decimal(str(value)), None
        except InvalidOperation:
            return None, None

    def _normalize_currency(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        return self._CURRENCY_ALIASES.get(normalized, normalized or None)
