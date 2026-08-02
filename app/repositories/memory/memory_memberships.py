from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from uuid import UUID

from app.domain.tenancy import Membership, TenantRole, utc_now
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.memberships import MembershipRepository


class MemoryMembershipRepository(MembershipRepository):
    """Deterministic in-memory repository for tenant memberships."""

    def __init__(self) -> None:
        """Initialize isolated membership storage."""
        self._memberships_by_id: dict[UUID, Membership] = {}
        self._membership_ids_by_user_tenant: dict[tuple[UUID, UUID], UUID] = {}

    async def create(self, membership: Membership) -> Membership:
        """Persist one membership while enforcing user/tenant uniqueness."""
        key = (membership.user_id, membership.tenant_id)
        existing_id = self._membership_ids_by_user_tenant.get(key)
        if existing_id is not None and existing_id != membership.id:
            msg = (
                "Membership already exists for user and tenant: "
                f"{membership.user_id}/{membership.tenant_id}."
            )
            raise RepositoryIdentityConflictError(msg)
        if membership.id in self._memberships_by_id:
            msg = f"Membership ID already exists: {membership.id}."
            raise RepositoryIdentityConflictError(msg)
        self._memberships_by_id[membership.id] = membership
        self._membership_ids_by_user_tenant[key] = membership.id
        return membership

    async def get_by_user_and_tenant(
        self,
        user_id: UUID,
        tenant_id: UUID,
    ) -> Membership | None:
        """Return one membership by user and tenant identity."""
        membership_id = self._membership_ids_by_user_tenant.get((user_id, tenant_id))
        if membership_id is None:
            return None
        return self._memberships_by_id[membership_id]

    async def list_for_user(self, user_id: UUID) -> Sequence[Membership]:
        """Return memberships for one user in insertion order."""
        return tuple(
            membership
            for membership in self._memberships_by_id.values()
            if membership.user_id == user_id
        )

    async def list_for_tenant(self, tenant_id: UUID) -> Sequence[Membership]:
        """Return memberships for one tenant in insertion order."""
        return tuple(
            membership
            for membership in self._memberships_by_id.values()
            if membership.tenant_id == tenant_id
        )

    async def update_role(
        self,
        user_id: UUID,
        tenant_id: UUID,
        role: TenantRole,
        expected_version: int,
    ) -> Membership | None:
        """Update a membership role when the expected version matches."""
        membership = await self.get_by_user_and_tenant(user_id, tenant_id)
        if membership is None or membership.version != expected_version:
            return None
        updated = replace(
            membership,
            role=role,
            updated_at=utc_now(),
            version=membership.version + 1,
        )
        self._memberships_by_id[membership.id] = updated
        return updated

    async def set_active(
        self,
        user_id: UUID,
        tenant_id: UUID,
        is_active: bool,
        expected_version: int,
    ) -> Membership | None:
        """Update active state when the expected version matches."""
        membership = await self.get_by_user_and_tenant(user_id, tenant_id)
        if membership is None or membership.version != expected_version:
            return None
        updated = replace(
            membership,
            is_active=is_active,
            updated_at=utc_now(),
            version=membership.version + 1,
        )
        self._memberships_by_id[membership.id] = updated
        return updated
