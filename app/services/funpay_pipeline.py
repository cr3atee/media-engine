from __future__ import annotations

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
        normalized = tuple(self._normalizer.normalize(list(extraction.items)))
        return MarketplaceIngestionResult(
            offers=normalized,
            evidence=extraction.evidence,
        )
