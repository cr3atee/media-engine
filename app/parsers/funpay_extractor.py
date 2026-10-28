from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlencode

from funpayparsers.exceptions import ParsingError
from funpayparsers.parsers.offer_previews_parser import OfferPreviewsParser
from funpayparsers.types.enums import Currency
from funpayparsers.types.offers import OfferPreview

from app.parsers.models import ParsedOffer

_BASE_OFFER_URL = "https://funpay.com/lots/offer"
_PRICE_QUANTUM = Decimal("0.01")


class FunPayExtractionError(RuntimeError):
    """Raised when a FunPay listing no longer matches the parser contract."""


class FunPayExtractor:
    """Map typed FunPay offer previews to marketplace-independent offers."""

    MARKETPLACE = "funpay"

    def extract(self, raw_response: str) -> list[ParsedOffer]:
        """Extract and deduplicate offers from a public FunPay listing page."""
        try:
            previews = OfferPreviewsParser(
                raw_response,
                empty_raw_source=True,
            ).parse()
        except ParsingError as exc:
            msg = "FunPay listing does not match the supported HTML contract"
            raise FunPayExtractionError(msg) from exc

        offers: list[ParsedOffer] = []
        seen_ids: set[str] = set()
        for preview in previews:
            offer = self._to_parsed_offer(preview)
            if offer.external_id is None or offer.external_id in seen_ids:
                continue
            seen_ids.add(offer.external_id)
            offers.append(offer)
        return offers

    def _to_parsed_offer(self, preview: OfferPreview) -> ParsedOffer:
        external_id = str(preview.id).strip()
        seller = preview.seller
        currency = preview.price.currency

        return ParsedOffer(
            marketplace=self.MARKETPLACE,
            external_id=external_id or None,
            title=self._clean_text(preview.title),
            url=self._offer_url(external_id),
            price=Decimal(str(preview.price.value)).quantize(
                _PRICE_QUANTUM,
                rounding=ROUND_HALF_UP,
            ),
            currency=None if currency is Currency.UNKNOWN else currency.value,
            seller_id=str(seller.id) if seller is not None else None,
            seller_name=(
                self._clean_text(seller.username) if seller is not None else None
            ),
        )

    @staticmethod
    def _offer_url(external_id: str) -> str | None:
        if not external_id:
            return None
        return f"{_BASE_OFFER_URL}?{urlencode({'id': external_id})}"

    @staticmethod
    def _clean_text(value: str | None) -> str | None:
        if value is None:
            return None
        text = " ".join(value.split())
        return text or None
