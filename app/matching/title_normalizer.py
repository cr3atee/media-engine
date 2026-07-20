from __future__ import annotations

import re


class TitleNormalizer:
    """Normalizes product titles before future matching steps."""

    _SEPARATORS_PATTERN = re.compile(r"[-_/|]+")
    _PUNCTUATION_PATTERN = re.compile(r"([^\w\s])\1+")
    _SPACES_PATTERN = re.compile(r"\s+")

    def normalize(self, title: str) -> str:
        """Return a deterministic normalized title string."""
        normalized = title.strip().lower()
        normalized = self._SEPARATORS_PATTERN.sub(" ", normalized)
        normalized = self._PUNCTUATION_PATTERN.sub(r"\1", normalized)
        normalized = self._SPACES_PATTERN.sub(" ", normalized)
        return normalized.strip()
