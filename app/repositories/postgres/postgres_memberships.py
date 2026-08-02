from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.tenancy import Membership, TenantRole, utc_now
from app.models.tenant_membership_record import TenantMembershipRecord
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.memberships import MembershipRepository


class PostgresMembershipRepository(MembershipRepository):
    """PostgreSQL-backed repository for tenant memberships."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a caller-owned session and transaction."""
        self._session = session

    async def create(self, membership: Membership) -> Membership:
        """Persist one membership while enforcing user/tenant uniqueness."""
        if await self._get_by_id(membership.id) is not None:
            msg = f"Membership ID already exists: {membership.id}."
            raise RepositoryIdentityConflictError(msg)
        if (
            await self.get_by_user_and_tenant(
                membership.user_id,
                membership.tenant_id,
            )
            is not None
        ):
            msg = (
                "Membership already exists for user and tenant: "
                f"{membership.user_id}/{membership.tenant_id}."
            )
            raise RepositoryIdentityConflictError(msg)
        self._session.add(
            TenantMembershipRecord(
                id=membership.id,
                user_id=membership.user_id,
                tenant_id=membership.tenant_id,
                role=membership.role.value,
                is_active=membership.is_active,
                joined_at=membership.joined_at,
                updated_at=membership.updated_at,
                version=membership.version,
            )
        )
        await self._session.flush()
        return membership

    async def get_by_user_and_tenant(
        self,
        user_id: UUID,
        tenant_id: UUID,
    ) -> Membership | None:
        """Return one membership by user and tenant identity."""
        result = await self._session.execute(
            select(TenantMembershipRecord).where(
                TenantMembershipRecord.user_id == user_id,
                TenantMembershipRecord.tenant_id == tenant_id,
            )
        )
        record = result.scalar_one_or_none()
        return _to_domain(record) if record is not None else None

    async def list_for_user(self, user_id: UUID) -> Sequence[Membership]:
        """Return memberships for one user in deterministic order."""
        result = await self._session.execute(
            select(TenantMembershipRecord)
            .where(TenantMembershipRecord.user_id == user_id)
            .order_by(TenantMembershipRecord.joined_at, TenantMembershipRecord.id)
        )
        return tuple(_to_domain(record) for record in result.scalars())

    async def list_for_tenant(self, tenant_id: UUID) -> Sequence[Membership]:
        """Return memberships for one tenant in deterministic order."""
        result = await self._session.execute(
            select(TenantMembershipRecord)
            .where(TenantMembershipRecord.tenant_id == tenant_id)
            .order_by(TenantMembershipRecord.joined_at, TenantMembershipRecord.id)
        )
        return tuple(_to_domain(record) for record in result.scalars())

    async def update_role(
        self,
        user_id: UUID,
        tenant_id: UUID,
        role: TenantRole,
        expected_version: int,
    ) -> Membership | None:
        """Update role when the expected version matches."""
        record = await self._get_record_by_user_and_tenant(user_id, tenant_id)
        if record is None or record.version != expected_version:
            return None
        record.role = role.value
        record.updated_at = utc_now()
        record.version += 1
        await self._session.flush()
        return _to_domain(record)

    async def set_active(
        self,
        user_id: UUID,
        tenant_id: UUID,
        is_active: bool,
        expected_version: int,
    ) -> Membership | None:
        """Update active state when the expected version matches."""
        record = await self._get_record_by_user_and_tenant(user_id, tenant_id)
        if record is None or record.version != expected_version:
            return None
        record.is_active = is_active
        record.updated_at = utc_now()
        record.version += 1
        await self._session.flush()
        return _to_domain(record)

    async def _get_by_id(self, membership_id: UUID) -> Membership | None:
        record = await self._session.get(TenantMembershipRecord, membership_id)
        return _to_domain(record) if record is not None else None

    async def _get_record_by_user_and_tenant(
        self,
        user_id: UUID,
        tenant_id: UUID,
    ) -> TenantMembershipRecord | None:
        result = await self._session.execute(
            select(TenantMembershipRecord).where(
                TenantMembershipRecord.user_id == user_id,
                TenantMembershipRecord.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()


def _to_domain(record: TenantMembershipRecord) -> Membership:
    return Membership(
        id=record.id,
        user_id=record.user_id,
        tenant_id=record.tenant_id,
        role=TenantRole(record.role),
        is_active=record.is_active,
        joined_at=record.joined_at,
        updated_at=record.updated_at,
        version=record.version,
    )
