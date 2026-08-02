from __future__ import annotations

from app.catalog.normalization.normalizer import CatalogNormalizer
from app.models.catalog_item import CatalogItem


class CatalogMatcher:
    """Matches raw marketplace titles to catalog items.

    Future versions can add fuzzy search, alias matching, embeddings, AI-based
    matching, and confidence scores for administrator review.
    """

    def __init__(self, normalizer: CatalogNormalizer | None = None) -> None:
        """Initialize the matcher with a catalog title normalizer."""
        self._normalizer = normalizer or CatalogNormalizer()

    def match(
        self,
        raw_title: str,
        catalog_items: list[CatalogItem],
    ) -> CatalogItem | None:
        """Return the first catalog item whose normalized name exactly matches."""
        normalized_title = self._normalizer.normalize("", raw_title)

        for item in catalog_items:
            normalized_name = self._normalizer.normalize("", item.name)
            if normalized_title == normalized_name:
                return item

        return None
