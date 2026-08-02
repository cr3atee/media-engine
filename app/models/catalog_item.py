from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(slots=True)
class CatalogItem:
    """Database-independent domain model for a catalog item."""

    id: UUID
    name: str
    aliases: list[str]
    category: str
    is_active: bool
    priority: int
    created_at: datetime
    updated_at: datetime
