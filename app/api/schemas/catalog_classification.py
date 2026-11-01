from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from app.api.schemas.common import ApiModel
from app.catalog.categories import CatalogCategoryCode


def _nonempty_text(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("Value must not be blank.")
    return normalized


def _optional_nonempty_text(value: str | None) -> str | None:
    if value is None:
        return None
    return _nonempty_text(value)


class CatalogSectionResponse(ApiModel):
    """One configured subsection available for verified source mappings."""

    code: str
    name: str
    offer_type: CatalogCategoryCode | None


class CatalogHubResponse(ApiModel):
    """One configured game or service hub and its allowed subsections."""

    code: str
    name: str
    sections: tuple[CatalogSectionResponse, ...]


class CatalogTaxonomyResponse(ApiModel):
    """Stable classification targets shared by runtime and seller tooling."""

    hubs: tuple[CatalogHubResponse, ...]


class CatalogSourceRuleResponse(ApiModel):
    """Tenant-safe source-category classification rule."""

    id: UUID
    tenant_id: UUID
    integration_id: UUID
    marketplace: str
    source_category_id: str
    source_category_name: str | None
    hub_code: str
    section_code: str
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=1)


class CatalogSourceCategoryResponse(ApiModel):
    """Observed marketplace category evidence available to map."""

    marketplace: str
    source_category_id: str
    source_category_name: str | None
    offer_count: int = Field(ge=1)


class CreateCatalogSourceRuleRequest(ApiModel):
    """Input for mapping observed marketplace evidence to one subsection."""

    marketplace: str = Field(min_length=1, max_length=64)
    source_category_id: str = Field(min_length=1, max_length=255)
    source_category_name: str | None = Field(default=None, max_length=500)
    hub_code: str = Field(min_length=1, max_length=64)
    section_code: str = Field(min_length=1, max_length=64)

    _normalize_marketplace = field_validator("marketplace")(_nonempty_text)
    _normalize_source_category_id = field_validator("source_category_id")(
        _nonempty_text
    )
    _normalize_source_category_name = field_validator("source_category_name")(
        _optional_nonempty_text
    )
    _normalize_hub_code = field_validator("hub_code")(_nonempty_text)
    _normalize_section_code = field_validator("section_code")(_nonempty_text)


class UpdateCatalogSourceRuleRequest(CreateCatalogSourceRuleRequest):
    """Expected-version correction for one persisted source mapping."""

    expected_version: int = Field(ge=1)
