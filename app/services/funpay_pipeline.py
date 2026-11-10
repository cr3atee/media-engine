from __future__ import annotations

from dataclasses import replace
from urllib.parse import urlparse

from app.parsers.funpay_extractor import FunPayExtractor
from app.parsers.funpay_fetcher import FunPayFetcher
from app.parsers.funpay_normalizer import FunPayNormalizer
from app.parsers.models import ParsedOffer
from app.services.marketplace_ingestion import MarketplaceIngestionResult


class FunPayPipeline:
    """Orchestrates fetching, extraction, and normalization for FunPay."""

    def __init__(
        self,
        *,
        fetcher: FunPayFetcher,
        extractor: FunPayExtractor,
        normalizer: FunPayNormalizer,
    ) -> None:
        """Initialize the pipeline with existing FunPay parser components."""
        self._fetcher = fetcher
        self._extractor = extractor
        self._normalizer = normalizer

    async def run(self, url: str = FunPayFetcher.DEFAULT_URL) -> list[ParsedOffer]:
        """Fetch and transform FunPay data into normalized parsed offers."""
        result = await self.ingest(url)
        return list(result.offers)

    async def ingest(
        self,
        url: str = FunPayFetcher.DEFAULT_URL,
    ) -> MarketplaceIngestionResult:
        """Return normalized offers and structural completeness evidence."""
        raw_response = await self._fetcher.fetch(url)
        extraction = self._extractor.extract_with_evidence(raw_response)
        source_category_id = funpay_source_category_id(self._fetcher.last_url or url)
        extracted = (
            tuple(
                replace(offer, source_category_id=source_category_id)
                for offer in extraction.items
            )
            if source_category_id is not None
            else extraction.items
        )
        normalized = tuple(self._normalizer.normalize(list(extracted)))
        return MarketplaceIngestionResult(
            offers=normalized,
            evidence=extraction.evidence,
        )


def funpay_source_category_id(url: str) -> str | None:
    """Return a category ID only from a trusted FunPay listing URL."""
    parsed = urlparse(url)
    if parsed.scheme.casefold() not in {"http", "https"}:
        return None
    if (parsed.hostname or "").casefold() not in {"funpay.com", "www.funpay.com"}:
        return None
    segments = tuple(segment for segment in parsed.path.split("/") if segment)
    plain_listing = len(segments) == 2 and segments[0].casefold() == "lots"
    localized_listing = (
        len(segments) == 3
        and len(segments[0]) == 2
        and segments[0].isalpha()
        and segments[1].casefold() == "lots"
    )
    if not plain_listing and not localized_listing:
        return None
    category_id = segments[-1].strip()
    return category_id if category_id.isdigit() else None
