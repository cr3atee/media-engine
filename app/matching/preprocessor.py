from __future__ import annotations

from app.matching.aliases import AliasEngine
from app.matching.stop_words import StopWordsFilter
from app.matching.title_normalizer import TitleNormalizer
from app.matching.tokenizer import TitleTokenizer


class MatchingPreprocessor:
    """Runs deterministic marketplace-independent title preprocessing."""

    def __init__(
        self,
        *,
        normalizer: TitleNormalizer | None = None,
        tokenizer: TitleTokenizer | None = None,
        stop_words_filter: StopWordsFilter | None = None,
        alias_engine: AliasEngine | None = None,
    ) -> None:
        """Initialize preprocessing with reusable matching components."""
        self._normalizer = normalizer or TitleNormalizer()
        self._tokenizer = tokenizer or TitleTokenizer()
        self._stop_words_filter = stop_words_filter or StopWordsFilter()
        self._alias_engine = alias_engine or AliasEngine()

    def process(self, title: str) -> tuple[str, ...]:
        """Return processed tokens for a marketplace product title."""
        normalized_title = self._normalizer.normalize(title)
        tokens = self._tokenizer.tokenize(normalized_title)
        filtered_tokens = self._stop_words_filter.filter(tokens)
        return self._alias_engine.expand(filtered_tokens)
