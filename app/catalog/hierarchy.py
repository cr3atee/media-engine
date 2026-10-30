from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.catalog.categories import CatalogCategoryCode

_CODE_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(slots=True, frozen=True)
class CatalogSection:
    """One verified subsection available inside a game or service hub."""

    code: str
    name: str
    offer_type: CatalogCategoryCode | None = None

    def __post_init__(self) -> None:
        """Normalize and validate the stable section identity."""
        object.__setattr__(self, "code", _require_code(self.code, "section code"))
        object.__setattr__(self, "name", _require_text(self.name, "section name"))


@dataclass(slots=True, frozen=True)
class CatalogHub:
    """One game or service containing its verified catalog subsections."""

    code: str
    name: str
    sections: tuple[CatalogSection, ...]

    def __post_init__(self) -> None:
        """Normalize the hub and reject ambiguous section definitions."""
        object.__setattr__(self, "code", _require_code(self.code, "hub code"))
        object.__setattr__(self, "name", _require_text(self.name, "hub name"))
        section_codes = [section.code for section in self.sections]
        if len(section_codes) != len(set(section_codes)):
            msg = f"Catalog hub {self.code!r} contains duplicate section codes."
            raise ValueError(msg)

    def section(self, code: str) -> CatalogSection | None:
        """Return a subsection by its stable code when it exists."""
        normalized = _require_code(code, "section code")
        return next(
            (section for section in self.sections if section.code == normalized),
            None,
        )


@dataclass(slots=True, frozen=True)
class SourceCategoryMapping:
    """Verified mapping from one marketplace category to a catalog subsection."""

    marketplace: str
    source_category_id: str
    hub_code: str
    section_code: str

    def __post_init__(self) -> None:
        """Normalize the source identity and target catalog codes."""
        object.__setattr__(
            self,
            "marketplace",
            _require_text(self.marketplace, "marketplace").casefold(),
        )
        object.__setattr__(
            self,
            "source_category_id",
            _require_text(self.source_category_id, "source category ID"),
        )
        object.__setattr__(
            self,
            "hub_code",
            _require_code(self.hub_code, "hub code"),
        )
        object.__setattr__(
            self,
            "section_code",
            _require_code(self.section_code, "section code"),
        )


@dataclass(slots=True, frozen=True)
class CatalogClassification:
    """Resolved game or service hub and its marketplace-specific subsection."""

    hub: CatalogHub
    section: CatalogSection


class CatalogClassifier:
    """Classify source categories using only explicit, verified mappings."""

    def __init__(
        self,
        hubs: Sequence[CatalogHub],
        mappings: Sequence[SourceCategoryMapping],
    ) -> None:
        """Build and validate an immutable deterministic classification index."""
        self._hubs = tuple(hubs)
        self._hubs_by_code = _index_hubs(self._hubs)
        self._classifications = self._index_mappings(mappings)

    @property
    def hubs(self) -> tuple[CatalogHub, ...]:
        """Return configured hubs in their intentional display order."""
        return self._hubs

    def classify(
        self,
        marketplace: str,
        source_category_id: str | None,
    ) -> CatalogClassification | None:
        """Return an exact classification or None without guessing from titles."""
        if source_category_id is None or not source_category_id.strip():
            return None
        normalized_marketplace = marketplace.strip().casefold()
        if not normalized_marketplace:
            return None
        return self._classifications.get(
            (normalized_marketplace, source_category_id.strip())
        )

    def _index_mappings(
        self,
        mappings: Sequence[SourceCategoryMapping],
    ) -> dict[tuple[str, str], CatalogClassification]:
        indexed: dict[tuple[str, str], CatalogClassification] = {}
        for mapping in mappings:
            source_key = (mapping.marketplace, mapping.source_category_id)
            if source_key in indexed:
                msg = (
                    "Duplicate marketplace source-category mapping: "
                    f"{mapping.marketplace}:{mapping.source_category_id}."
                )
                raise ValueError(msg)

            hub = self._hubs_by_code.get(mapping.hub_code)
            if hub is None:
                msg = f"Unknown catalog hub in source mapping: {mapping.hub_code}."
                raise ValueError(msg)
            section = hub.section(mapping.section_code)
            if section is None:
                msg = (
                    f"Unknown section {mapping.section_code!r} for catalog hub "
                    f"{mapping.hub_code!r}."
                )
                raise ValueError(msg)
            indexed[source_key] = CatalogClassification(hub=hub, section=section)
        return indexed


def _index_hubs(hubs: Sequence[CatalogHub]) -> dict[str, CatalogHub]:
    indexed: dict[str, CatalogHub] = {}
    for hub in hubs:
        if hub.code in indexed:
            msg = f"Duplicate catalog hub code: {hub.code}."
            raise ValueError(msg)
        indexed[hub.code] = hub
    return indexed


def _require_code(value: str, field_name: str) -> str:
    normalized = value.strip().casefold()
    if not _CODE_PATTERN.fullmatch(normalized):
        msg = f"{field_name.capitalize()} must be a non-empty lowercase slug."
        raise ValueError(msg)
    return normalized


def _require_text(value: str, field_name: str) -> str:
    normalized = " ".join(value.strip().split())
    if not normalized:
        msg = f"{field_name.capitalize()} must not be empty."
        raise ValueError(msg)
    return normalized
