from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.matching.confidence import ConfidenceEngine


def main() -> None:
    """Print matching decisions for sample similarity scores."""
    confidence_engine = ConfidenceEngine()
    similarities = (1.0, 0.95, 0.94, 0.80, 0.79, 0.0)

    for similarity in similarities:
        decision = confidence_engine.classify(similarity)
        print(f"{similarity:.2f} -> {decision.value}")


if __name__ == "__main__":
    main()
