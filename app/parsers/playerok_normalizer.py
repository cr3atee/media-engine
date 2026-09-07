from __future__ import annotations

from dataclasses import replace

from app.parsers.models import ParsedOffer
from app.parsers.normalizers import normalize_currency, normalize_text


class PlayerokNormalizer:
    """Normalizes extracted Playerok offers using shared parser rules."""

    MARKETPLACE = "playerok"

    def normalize(self, offers: list[ParsedOffer]) -> list[ParsedOffer]:
        """Return normalized copies of the supplied Playerok offers."""
        return [self._normalize_offer(offer) for offer in offers]

    def _normalize_offer(self, offer: ParsedOffer) -> ParsedOffer:
        return replace(
            offer,
            marketplace=self.MARKETPLACE,
            external_id=normalize_text(offer.external_id),
            title=normalize_text(offer.title),
            url=normalize_text(offer.url),
            currency=normalize_currency(offer.currency),
            seller_id=normalize_text(offer.seller_id),
            seller_name=normalize_text(offer.seller_name),
        )
