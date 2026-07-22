from __future__ import annotations

from app.parsers.models import ParsedOffer
from app.parsers.playerok_extractor import PlayerokExtractor
from app.parsers.playerok_fetcher import PlayerokFetcher
from app.parsers.playerok_normalizer import PlayerokNormalizer


class PlayerokPipeline:
    """Orchestrates fetching, extraction, and normalization for Playerok."""

    def __init__(
        self,
        *,
        fetcher: PlayerokFetcher,
        extractor: PlayerokExtractor,
        normalizer: PlayerokNormalizer,
    ) -> None:
        """Initialize the pipeline with existing Playerok components."""
        self._fetcher = fetcher
        self._extractor = extractor
        self._normalizer = normalizer

    async def run(
        self,
        url: str = PlayerokFetcher.DEFAULT_URL,
    ) -> list[ParsedOffer]:
        """Fetch and transform Playerok data into normalized parsed offers."""
        raw_response = await self._fetcher.fetch(url)
        extracted_offers = self._extractor.extract(raw_response)
        return self._normalizer.normalize(extracted_offers)
