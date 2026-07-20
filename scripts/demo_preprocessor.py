from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.matching.preprocessor import MatchingPreprocessor


def main() -> None:
    """Print processed tokens for sample marketplace product titles."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    preprocessor = MatchingPreprocessor()
    examples = (
        "MC Premium Steam Account",
        "minecraftjava digital key",
        "GTA5 Global Edition",
        "CS2 Official License",
        "PUBG Online Gift",
    )

    for title in examples:
        print(f"Original title: {title}")
        print("↓")
        print(f"Processed tokens: {preprocessor.process(title)}")
        print()


if __name__ == "__main__":
    main()
