"""Verified catalog taxonomy shared by ingestion and seller tooling."""

from __future__ import annotations

from typing import Final

from app.catalog.categories import MVP_CATALOG_CATEGORIES
from app.catalog.hierarchy import CatalogHub, CatalogSection

MVP_CATALOG_HUBS: Final[tuple[CatalogHub, ...]] = (
    CatalogHub(
        code="minecraft",
        name="Minecraft",
        sections=tuple(
            CatalogSection(
                code=category.code,
                name=category.name,
                offer_type=category.code,
            )
            for category in MVP_CATALOG_CATEGORIES
        ),
    ),
)
