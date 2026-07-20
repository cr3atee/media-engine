from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.matching.title_normalizer import TitleNormalizer


def main() -> None:
    """Print normalized forms of sample marketplace titles."""
    examples = (
        "Minecraft Premium",
        "minecraft-premium",
        "Minecraft / Premium",
        "Minecraft_Premium",
        "MINECRAFT    PREMIUM",
    )
    normalizer = TitleNormalizer()

    for title in examples:
        print(f"{title} -> {normalizer.normalize(title)}")


if __name__ == "__main__":
    main()
