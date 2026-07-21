from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.matching.similarity import SimilarityEngine


def main() -> None:
    """Print similarity scores for sample token tuples."""
    similarity_engine = SimilarityEngine()
    examples = (
        (("minecraft", "premium"), ("minecraft", "premium")),
        (("minecraft", "premium"), ("minecraft", "java")),
        (("counter", "strike", "2"), ("counter", "strike")),
        (("minecraft",), ("gta", "v")),
    )

    for left, right in examples:
        similarity = similarity_engine.calculate(left, right)
        print(f"{left} <-> {right}: {similarity:.2f}")


if __name__ == "__main__":
    main()
