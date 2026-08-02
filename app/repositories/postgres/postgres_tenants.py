from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.tenancy import (
    LEGACY_TENANT_ID,
    LEGACY_TENANT_SLUG,
    Tenant,
    normalize_tenant_slug,
    utc_now,
)
from app.models.tenant_record import TenantRecord
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.tenants import TenantRepository


class PostgresTenantRepository(TenantRepository):
    """PostgreSQL-backed repository for tenant identities."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a caller-owned session and transaction."""
        self._session = session

    async def create(self, tenant: Tenant) -> Tenant:
        """Persist one tenant while enforcing slug uniqueness."""
        if await self.get_by_id(tenant.id) is not None:
            msg = f"Tenant ID already exists: {tenant.id}."
            raise RepositoryIdentityConflictError(msg)
        if await self.get_by_slug(tenant.slug) is not None:
            msg = f"Tenant slug already exists: {tenant.slug}."
            raise RepositoryIdentityConflictError(msg)
        self._session.add(
            TenantRecord(
                id=tenant.id,
                name=tenant.name,
                slug=tenant.slug,
                is_active=tenant.is_active,
                created_at=tenant.created_at,
                updated_at=tenant.updated_at,
                version=tenant.version,
            )
        )
        await self._session.flush()
        return tenant

    async def get_by_id(self, tenant_id: UUID) -> Tenant | None:
        """Return one tenant by technical identifier."""
        record = await self._session.get(TenantRecord, tenant_id)
        return _to_domain(record) if record is not None else None

    async def get_by_slug(self, slug: str) -> Tenant | None:
        """Return one tenant by stable slug."""
        normalized = slug.strip().lower()
        result = await self._session.execute(
            select(TenantRecord).where(
                TenantRecord.slug
                == normalize_tenant_slug(
                    slug,
                    allow_legacy=normalized == LEGACY_TENANT_SLUG,
                )
            )
        )
        record = result.scalar_one_or_none()
        return _to_domain(record) if record is not None else None

    async def get_legacy_tenant(self) -> Tenant | None:
        """Return the deterministic legacy tenant."""
        return await self.get_by_id(LEGACY_TENANT_ID)

    async def set_active(
        self,
        tenant_id: UUID,
        is_active: bool,
        expected_version: int,
    ) -> Tenant | None:
        """Update active state when the expected version matches."""
        record = await self._session.get(TenantRecord, tenant_id)
        if record is None or record.version != expected_version:
            return None
        record.is_active = is_active
        record.updated_at = utc_now()
        record.version += 1
        await self._session.flush()
        return _to_domain(record)


def _to_domain(record: TenantRecord) -> Tenant:
    return Tenant(
        id=record.id,
        name=record.name,
        slug=record.slug,
        is_active=record.is_active,
        created_at=record.created_at,
        updated_at=record.updated_at,
        version=record.version,
    )
