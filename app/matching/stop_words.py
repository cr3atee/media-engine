from __future__ import annotations


class StopWordsFilter:
    """Filters known marketplace noise words from normalized title tokens."""

    STOP_WORDS = frozenset(
        (
            "key",
            "keys",
            "gift",
            "gifts",
            "account",
            "accounts",
            "global",
            "edition",
            "steam",
            "online",
            "official",
            "license",
            "digital",
        ),
    )

    def filter(self, tokens: tuple[str, ...]) -> tuple[str, ...]:
        """Return tokens with known marketplace noise words removed."""
        return tuple(token for token in tokens if token not in self.STOP_WORDS)
