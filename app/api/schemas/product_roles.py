"""Strict role commands; the caller cannot provide their own actor or scope."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.domain.product_access import ProductRole


class ProductRoleRequest(ApiModel):
    """One explicit role change bound to the expected user version."""

    role: ProductRole
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class ProductRoleResponse(ApiModel):
    """Minimal identity state needed to issue an optimistic role command."""

    id: UUID
    product_role: ProductRole
    enabled: bool
    version: int


class ProductRoleActionResponse(ApiModel):
    """Public-to-admin audit view; retry fingerprints remain internal."""

    id: UUID
    user_id: UUID
    actor_user_id: UUID | None
    actor_key: str
    previous_role: ProductRole
    resulting_role: ProductRole
    expected_version: int
    resulting_version: int
    reason: str
    created_at: datetime
