from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urlparse

from funpayparsers.exceptions import ParsingError
from funpayparsers.parsers.offer_previews_parser import OfferPreviewsParser
from funpayparsers.types.enums import Currency
from funpayparsers.types.offers import OfferPreview

from app.parsers.models import ParsedOffer
from app.parsers.source_snapshot import SourceExtraction, SourceSnapshotEvidence

_BASE_OFFER_URL = "https://funpay.com/lots/offer"
_PRICE_QUANTUM = Decimal("0.01")


class FunPayExtractionError(RuntimeError):
    """Raised when a FunPay listing no longer matches the parser contract."""


class FunPayExtractor:
    """Map typed FunPay offer previews to marketplace-independent offers."""

    MARKETPLACE = "funpay"

    def extract(self, raw_response: str) -> list[ParsedOffer]:
        """Extract and deduplicate offers from a public FunPay listing page."""
        return list(self.extract_with_evidence(raw_response).items)

    def extract_with_evidence(
        self,
        raw_response: str,
    ) -> SourceExtraction[ParsedOffer]:
        """Extract offers and audit whether the listing response is complete."""
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

        audit = _FunPayListingAudit.inspect(raw_response)
        parsed_ids = frozenset(
            offer.external_id for offer in offers if offer.external_id is not None
        )
        return SourceExtraction(
            items=tuple(offers),
            evidence=self._build_evidence(audit, parsed_ids, len(offers)),
        )

    def _build_evidence(
        self,
        audit: _FunPayListingAudit,
        parsed_ids: frozenset[str],
        parsed_items: int,
    ) -> SourceSnapshotEvidence:
        source_items = len(audit.offer_ids)
        reason: str | None = None
        if not audit.html_closed:
            reason = "FunPay response is not a closed HTML document."
        elif audit.showcase_tables != 1:
            reason = (
                "FunPay response must contain exactly one showcase table; "
                f"found {audit.showcase_tables}."
            )
        elif audit.pagination_detected:
            reason = "FunPay response exposes a pagination control."
        elif audit.invalid_offer_anchors:
            reason = "FunPay response contains offer anchors without a stable identity."
        elif audit.offer_ids != parsed_ids:
            reason = "FunPay source identities do not match extracted offers."

        if reason is not None:
            return SourceSnapshotEvidence(
                source_items=source_items,
                parsed_items=parsed_items,
                complete=False,
                reason=reason,
            )
        return SourceSnapshotEvidence(
            source_items=source_items,
            parsed_items=parsed_items,
            complete=True,
            reason=(
                "FunPay returned one closed, unpaginated showcase with full "
                "offer identity coverage."
            ),
        )

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


class _FunPayListingAudit(HTMLParser):
    """Audit source identities and pagination without parsing business fields."""

    _PAGINATION_CLASSES = frozenset(
        {"load-more", "pager", "pagination", "showcase-load-more"}
    )

    def __init__(self) -> None:
        super().__init__()
        self.offer_ids: set[str] = set()
        self.invalid_offer_anchors = 0
        self.showcase_tables = 0
        self.pagination_detected = False
        self.html_closed = False

    @classmethod
    def inspect(cls, html: str) -> _FunPayListingAudit:
        """Return a structural audit of one FunPay listing document."""
        audit = cls()
        audit.feed(html)
        audit.close()
        return audit

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = {name.lower(): value for name, value in attrs}
        classes = frozenset((attributes.get("class") or "").split())
        if "showcase-table" in classes:
            self.showcase_tables += 1

        rel = frozenset((attributes.get("rel") or "").lower().split())
        has_pagination_class = any(
            class_name in self._PAGINATION_CLASSES
            or class_name.startswith("pagination-")
            or class_name.startswith("pager-")
            for class_name in classes
        )
        if (
            "next" in rel
            or has_pagination_class
            or attributes.get("data-next-page") is not None
        ):
            self.pagination_detected = True

        if tag.lower() != "a" or "tc-item" not in classes:
            return

        href_id = self._offer_id_from_href(attributes.get("href"))
        data_id = self._clean_identity(attributes.get("data-offer"))
        if href_id is not None and data_id is not None and href_id != data_id:
            self.invalid_offer_anchors += 1
            return
        identity = data_id or href_id
        if identity is None:
            self.invalid_offer_anchors += 1
            return
        self.offer_ids.add(identity)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "html":
            self.html_closed = True

    @classmethod
    def _offer_id_from_href(cls, href: str | None) -> str | None:
        if href is None:
            return None
        parsed = urlparse(href)
        if not parsed.path.rstrip("/").endswith("/lots/offer"):
            return None
        values = parse_qs(parsed.query).get("id", ())
        if len(values) != 1:
            return None
        return cls._clean_identity(values[0])

    @staticmethod
    def _clean_identity(value: str | None) -> str | None:
        if value is None:
            return None
        identity = value.strip()
        if not identity.isdigit():
            return None
        return identity
