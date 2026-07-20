from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.matching.aliases import AliasEngine
from app.matching.title_normalizer import TitleNormalizer
from app.matching.tokenizer import TitleTokenizer


def main() -> None:
    """Print title tokens before and after alias expansion."""
    normalizer = TitleNormalizer()
    tokenizer = TitleTokenizer()
    alias_engine = AliasEngine()
    examples = (
        "MC Premium",
        "minecraftjava account",
        "GTA5 global",
        "CS2 key",
        "PUBG online",
    )

    for title in examples:
        tokens = tokenizer.tokenize(normalizer.normalize(title))
        expanded_tokens = alias_engine.expand(tokens)
        print(f"{title}")
        print(f"Before: {tokens}")
        print(f"After:  {expanded_tokens}")
        print()


if __name__ == "__main__":
    main()
