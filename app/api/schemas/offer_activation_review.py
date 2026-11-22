"""Strict request and source-snapshot contracts for activation review."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Self
from uuid import UUID

from pydantic import Field, StrictBool, StrictInt, model_validator

from app.api.schemas.common import ApiModel
from app.domain.activation_conditions import (
    AccountRequirement,
    ActivationConditions,
    DeliveryMethod,
)


class ActivationConditionsPayload(ApiModel):
    """Require every fact explicitly; null whole profiles mean unknown."""

    version: StrictInt = Field(default=1, ge=1, le=1)
    regions: list[str] = Field(min_length=1, max_length=250)
    excluded_regions: list[str] = Field(max_length=249)
    device: str = Field(min_length=1, max_length=64)
    plan: str = Field(min_length=1, max_length=64)
    period: str = Field(min_length=1, max_length=64)
    delivery_method: DeliveryMethod
    account_requirement: AccountRequirement
    vpn_required: StrictBool
    activation_window_seconds: StrictInt | None = Field(ge=1)

    def to_domain(self) -> ActivationConditions:
        """Delegate condition normalization and invariants to the domain value."""
        return ActivationConditions(
            regions=tuple(self.regions),
            excluded_regions=tuple(self.excluded_regions),
            device=self.device,
            plan=self.plan,
            period=self.period,
            delivery_method=self.delivery_method,
            account_requirement=self.account_requirement,
            vpn_required=self.vpn_required,
            activation_window_seconds=self.activation_window_seconds,
        )

    @model_validator(mode="after")
    def validate_conditions(self) -> Self:
        """Reject incompatible structure instead of creating permissive defaults."""
        self.to_domain()
        return self


class OfferActivationReviewRequest(ApiModel):
    """Bind a reviewed profile to the source snapshot shown to the operator."""

    offer_id: UUID
    expected_version: StrictInt = Field(ge=1)
    expected_source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    conditions: ActivationConditionsPayload | None
    reason: str = Field(min_length=1, max_length=2000)


class OfferActivationReviewResponse(ApiModel):
    """Tenant-scoped active offer facts and its latest condition audit revision."""

    offer_id: UUID
    tenant_id: UUID
    marketplace: str
    external_id: str
    title: str | None
    url: str | None
    price: Decimal | None
    currency: str | None
    canonical_product_id: UUID | None
    version: int
    source_fingerprint: str
    reviewed_at: datetime | None
    conditions: ActivationConditionsPayload | None
