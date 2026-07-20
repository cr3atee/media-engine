from __future__ import annotations


class AliasEngine:
    """Expands known marketplace title aliases into canonical token forms."""

    ALIASES = {
        "mc": "minecraft",
        "minecraftjava": "minecraft",
        "gta5": "gta v",
        "cs2": "counter strike 2",
        "pubg": "playerunknowns battlegrounds",
    }

    def expand_token(self, token: str) -> str:
        """Return an expanded alias token, or the original token if unknown."""
        return self.ALIASES.get(token, token)

    def expand(self, tokens: tuple[str, ...]) -> tuple[str, ...]:
        """Return tokens with known aliases expanded while preserving order."""
        expanded_tokens: list[str] = []
        for token in tokens:
            expanded_tokens.extend(self.expand_token(token).split())
        return tuple(expanded_tokens)
