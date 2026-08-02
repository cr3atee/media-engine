from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from uuid import UUID

from app.domain.tenancy import Membership, TenantRole
from app.repositories.base import BaseRepository


class MembershipRepository(BaseRepository):
    """Abstract storage contract for tenant membership and role grants."""

    @abstractmethod
    async def create(self, membership: Membership) -> Membership:
        """Persist one user-to-tenant membership."""

    @abstractmethod
    async def get_by_user_and_tenant(
        self,
        user_id: UUID,
        tenant_id: UUID,
    ) -> Membership | None:
        """Return a membership for one user and tenant."""

    @abstractmethod
    async def list_for_user(self, user_id: UUID) -> Sequence[Membership]:
        """Return memberships for one user in deterministic order."""

    @abstractmethod
    async def list_for_tenant(self, tenant_id: UUID) -> Sequence[Membership]:
        """Return memberships for one tenant in deterministic order."""

    @abstractmethod
    async def update_role(
        self,
        user_id: UUID,
        tenant_id: UUID,
        role: TenantRole,
        expected_version: int,
    ) -> Membership | None:
        """Update a membership role using optimistic version guarding."""

    @abstractmethod
    async def set_active(
        self,
        user_id: UUID,
        tenant_id: UUID,
        is_active: bool,
        expected_version: int,
    ) -> Membership | None:
        """Update active state using optimistic version guarding."""
