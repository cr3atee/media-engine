from __future__ import annotations

from typing import TypeAlias

from app.models.catalog_item import CatalogItem

CatalogItems: TypeAlias = list[CatalogItem]


class CatalogNormalizer:
    """Normalizes marketplace product titles before catalog matching.

    In future iterations this class will remove noisy words, work with aliases,
    normalize product names, compare similar products, and prepare normalized
    titles for CatalogItem lookup.
    """

    def normalize(self, marketplace: str, raw_title: str) -> str:
        """Return a minimally normalized product title."""
        return " ".join(raw_title.split()).lower()
