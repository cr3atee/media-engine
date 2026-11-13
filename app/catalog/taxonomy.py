"""Verified catalog taxonomy shared by ingestion and seller tooling."""

from __future__ import annotations

from typing import Final

from app.catalog.categories import MVP_CATALOG_CATEGORIES, category_by_code
from app.catalog.hierarchy import CatalogHub, CatalogSection


def _subscription_hub(code: str, name: str) -> CatalogHub:
    """Build one service hub backed by the stable subscription offer type."""
    subscriptions = category_by_code("subscriptions")
    return CatalogHub(
        code=code,
        name=name,
        sections=(
            CatalogSection(
                code=subscriptions.code,
                name=subscriptions.name,
                offer_type=subscriptions.code,
            ),
        ),
    )


MVP_CATALOG_HUBS: Final[tuple[CatalogHub, ...]] = (
    _subscription_hub("exitlag", "ExitLag"),
    _subscription_hub("duolingo", "Duolingo"),
    _subscription_hub("spotify", "Spotify"),
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
