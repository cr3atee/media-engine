from __future__ import annotations

from collections.abc import Sequence

from app.comparator.result import ComparisonResult
from app.parsers.models import ParsedOffer
from app.parsers.playerok_extractor import PlayerokExtractor
from app.parsers.playerok_fetcher import PlayerokFetcher
from app.parsers.playerok_normalizer import PlayerokNormalizer
from app.services.marketplace_pipeline import MarketplacePipeline


class PlayerokPipeline:
    """Orchestrates fetching, extraction, and normalization for Playerok."""

    def __init__(
        self,
        *,
        fetcher: PlayerokFetcher,
        extractor: PlayerokExtractor,
        normalizer: PlayerokNormalizer,
        comparison_pipeline: MarketplacePipeline | None = None,
    ) -> None:
        """Initialize the pipeline with existing Playerok components."""
        self._fetcher = fetcher
        self._extractor = extractor
        self._normalizer = normalizer
        self._comparison_pipeline = comparison_pipeline

    async def run(
        self,
        url: str = PlayerokFetcher.DEFAULT_URL,
    ) -> list[ParsedOffer]:
        """Fetch and transform Playerok data into normalized parsed offers."""
        raw_response = await self._fetcher.fetch(url)
        extracted_offers = self._extractor.extract(raw_response)
        return self._normalizer.normalize(extracted_offers)

    async def run_comparison(
        self,
        url: str = PlayerokFetcher.DEFAULT_URL,
    ) -> list[ComparisonResult]:
        """Fetch Playerok offers and return unified comparison results."""
        if self._comparison_pipeline is None:
            msg = "PlayerokPipeline requires a comparison pipeline."
            raise RuntimeError(msg)

        parsed_offers = await self.run(url)
        return self.compare_offers(parsed_offers)

    def compare_offers(
        self,
        parsed_offers: Sequence[ParsedOffer],
    ) -> list[ComparisonResult]:
        """Return unified comparison results for normalized marketplace offers."""
        if self._comparison_pipeline is None:
            msg = "PlayerokPipeline requires a comparison pipeline."
            raise RuntimeError(msg)

        return self._comparison_pipeline.compare_offers(parsed_offers)

    def compare_repository_offers(self) -> list[ComparisonResult]:
        """Return unified comparison results from repository-backed offers."""
        if self._comparison_pipeline is None:
            msg = "PlayerokPipeline requires a comparison pipeline."
            raise RuntimeError(msg)

        return self._comparison_pipeline.compare_repository_offers()
