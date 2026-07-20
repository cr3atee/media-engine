from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.matching.stop_words import StopWordsFilter
from app.matching.title_normalizer import TitleNormalizer
from app.matching.tokenizer import TitleTokenizer


def main() -> None:
    """Print title tokens before and after stop-word filtering."""
    normalizer = TitleNormalizer()
    tokenizer = TitleTokenizer()
    stop_words_filter = StopWordsFilter()
    examples = (
        "Minecraft Premium Steam Account",
        "Elden Ring Digital Key Global",
        "Roblox Gift Official",
        "Cyberpunk 2077 Edition",
    )

    for title in examples:
        tokens = tokenizer.tokenize(normalizer.normalize(title))
        filtered_tokens = stop_words_filter.filter(tokens)
        print(f"{title}")
        print(f"Before: {tokens}")
        print(f"After:  {filtered_tokens}")
        print()


if __name__ == "__main__":
    main()
