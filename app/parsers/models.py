from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.domain.tenancy import LEGACY_TENANT_ID


@dataclass(slots=True)
class RawMarketplaceOffer:
    """Typed raw marketplace offer before domain normalization."""

    id_goods: int
    name: str
    url: str
    seller_name: str
    id_section: int
    image: str | None = None
    price: float | None = None
    currency: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, kw_only=True)
class ParsedOffer:
    """Raw marketplace offer extracted by a source parser."""

    marketplace: str
    external_id: str | None
    title: str | None
    url: str | None
    price: Decimal | None
    currency: str | None
    seller_id: str | None = None
    seller_name: str | None = None
    source_category_id: str | None = None
    source_category_name: str | None = None
    catalog_hub_code: str | None = None
    catalog_section_code: str | None = None
    catalog_source_rule_id: UUID | None = None
    canonical_product_id: UUID | None = None
    tenant_id: UUID = LEGACY_TENANT_ID
