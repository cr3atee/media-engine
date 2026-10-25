"""Product-level identity is independent of workspace membership permissions."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ProductRole(StrEnum):
    """Explicit product roles, never an ordered privilege hierarchy."""

    USER = "user"
    PARTNER = "partner"
    MODERATOR = "moderator"
    ADMIN = "admin"


class LastProductAdminError(ValueError):
    """The last enabled product administrator cannot be removed or disabled."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ProductRoleAction:
    """Immutable accepted role command, including its idempotent result."""

    id: UUID
    user_id: UUID
    actor_user_id: UUID | None
    actor_key: str
    previous_role: ProductRole
    resulting_role: ProductRole
    expected_version: int
    resulting_version: int
    reason: str
    idempotency_key: str
    fingerprint: str
    created_at: datetime
