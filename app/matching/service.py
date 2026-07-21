from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.matching.confidence import ConfidenceEngine, MatchDecision
from app.matching.preprocessor import MatchingPreprocessor
from app.matching.similarity import SimilarityEngine
from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer


@dataclass(slots=True)
class MatchResult:
    """Result of matching one parsed offer to canonical products."""

    decision: MatchDecision
    similarity: float
    canonical_product: CanonicalProduct | None


class MatchingService:
    """Matches marketplace offers to canonical products deterministically."""

    def __init__(
        self,
        *,
        preprocessor: MatchingPreprocessor | None = None,
        similarity_engine: SimilarityEngine | None = None,
        confidence_engine: ConfidenceEngine | None = None,
    ) -> None:
        """Initialize matching service with reusable matching components."""
        self._preprocessor = preprocessor or MatchingPreprocessor()
        self._similarity_engine = similarity_engine or SimilarityEngine()
        self._confidence_engine = confidence_engine or ConfidenceEngine()

    def match(
        self,
        offer: ParsedOffer,
        candidates: Sequence[CanonicalProduct],
    ) -> MatchResult:
        """Return the best deterministic match for a parsed marketplace offer."""
        if not candidates:
            return MatchResult(
                decision=MatchDecision.NO_MATCH,
                similarity=0.0,
                canonical_product=None,
            )

        offer_tokens = self._preprocessor.process(offer.title or "")
        best_similarity = 0.0
        best_candidate: CanonicalProduct | None = None

        for candidate in candidates:
            candidate_tokens = self._preprocessor.process(candidate.name)
            similarity = self._similarity_engine.calculate(
                offer_tokens,
                candidate_tokens,
            )
            if best_candidate is None or similarity > best_similarity:
                best_similarity = similarity
                best_candidate = candidate

        return MatchResult(
            decision=self._confidence_engine.classify(best_similarity),
            similarity=best_similarity,
            canonical_product=best_candidate,
        )
