from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(slots=True, frozen=True)
class CanonicalProduct:
    """Marketplace-independent product identity used across source offers."""

    id: UUID
    name: str
    category: str | None
    aliases: tuple[str, ...]
