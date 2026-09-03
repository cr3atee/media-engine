from __future__ import annotations

from app.parsers.funpay_extractor import FunPayExtractor
from app.parsers.funpay_fetcher import FunPayFetcher
from app.parsers.funpay_normalizer import FunPayNormalizer
from app.parsers.models import ParsedOffer


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
        raw_response = await self._fetcher.fetch(url)
        extracted_offers = self._extractor.extract(raw_response)
        return self._normalizer.normalize(extracted_offers)
