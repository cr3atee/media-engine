from __future__ import annotations

from app.models.catalog_item import CatalogItem


class CatalogBuilder:
    """Suggests catalog intelligence actions for product titles.

    In future iterations this class will search for similar products, determine
    whether an existing CatalogItem already matches a title, suggest creating a
    new catalog item, suggest merging related products, work with aliases, and
    prepare catalog moderation suggestions for an administrator.
    """

    def suggest(self, title: str) -> list[CatalogItem]:
        """Return catalog item suggestions for a source product title."""
        return []
