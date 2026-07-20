from __future__ import annotations


class TitleTokenizer:
    """Tokenizes already-normalized product titles for future matching steps."""

    def tokenize(self, normalized_title: str) -> tuple[str, ...]:
        """Split a normalized title into ordered non-empty whitespace tokens."""
        return tuple(token for token in normalized_title.split() if token)
