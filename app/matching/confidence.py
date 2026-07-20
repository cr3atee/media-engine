from __future__ import annotations

from enum import Enum


class MatchDecision(str, Enum):
    """Deterministic matching decision categories."""

    AUTO_MATCH = "auto_match"
    REVIEW = "review"
    NO_MATCH = "no_match"


class ConfidenceEngine:
    """Classifies similarity scores into matching decisions."""

    AUTO_MATCH_THRESHOLD = 0.95
    REVIEW_THRESHOLD = 0.80

    def classify(self, similarity: float) -> MatchDecision:
        """Return a deterministic match decision for a similarity score."""
        if not 0.0 <= similarity <= 1.0:
            msg = "Similarity must be within [0.0, 1.0]."
            raise ValueError(msg)

        if similarity >= self.AUTO_MATCH_THRESHOLD:
            return MatchDecision.AUTO_MATCH
        if similarity >= self.REVIEW_THRESHOLD:
            return MatchDecision.REVIEW
        return MatchDecision.NO_MATCH
