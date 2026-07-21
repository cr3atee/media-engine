from __future__ import annotations


class SimilarityEngine:
    """Calculates deterministic similarity between token sequences."""

    def calculate(
        self,
        left: tuple[str, ...],
        right: tuple[str, ...],
    ) -> float:
        """Return Jaccard similarity for two token tuples."""
        left_tokens = set(left)
        right_tokens = set(right)
        if not left_tokens and not right_tokens:
            return 1.0
        if not left_tokens or not right_tokens:
            return 0.0

        intersection_size = len(left_tokens & right_tokens)
        union_size = len(left_tokens | right_tokens)
        return intersection_size / union_size
