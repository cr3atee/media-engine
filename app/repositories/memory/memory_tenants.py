from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from app.domain.tenancy import (
    LEGACY_TENANT_ID,
    LEGACY_TENANT_SLUG,
    Tenant,
    normalize_tenant_slug,
    utc_now,
)
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.tenants import TenantRepository


class MemoryTenantRepository(TenantRepository):
    """Deterministic in-memory repository for tenant identities."""

    def __init__(self) -> None:
        """Initialize isolated tenant storage."""
        self._tenants_by_id: dict[UUID, Tenant] = {}
        self._tenant_ids_by_slug: dict[str, UUID] = {}

    async def create(self, tenant: Tenant) -> Tenant:
        """Persist one tenant while enforcing slug uniqueness."""
        slug = normalize_tenant_slug(
            tenant.slug,
            allow_legacy=tenant.id == LEGACY_TENANT_ID,
        )
        existing_id = self._tenant_ids_by_slug.get(slug)
        if existing_id is not None and existing_id != tenant.id:
            msg = f"Tenant slug already exists: {slug}."
            raise RepositoryIdentityConflictError(msg)
        if tenant.id in self._tenants_by_id:
            msg = f"Tenant ID already exists: {tenant.id}."
            raise RepositoryIdentityConflictError(msg)
        self._tenants_by_id[tenant.id] = tenant
        self._tenant_ids_by_slug[slug] = tenant.id
        return tenant

    async def get_by_id(self, tenant_id: UUID) -> Tenant | None:
        """Return one tenant by technical identifier."""
        return self._tenants_by_id.get(tenant_id)

    async def get_by_slug(self, slug: str) -> Tenant | None:
        """Return one tenant by stable slug."""
        normalized = slug.strip().lower()
        tenant_id = self._tenant_ids_by_slug.get(
            normalize_tenant_slug(
                slug,
                allow_legacy=normalized == LEGACY_TENANT_SLUG,
            )
        )
        return self._tenants_by_id.get(tenant_id) if tenant_id is not None else None

    async def get_legacy_tenant(self) -> Tenant | None:
        """Return the deterministic legacy tenant when it exists."""
        return self._tenants_by_id.get(LEGACY_TENANT_ID)

    async def set_active(
        self,
        tenant_id: UUID,
        is_active: bool,
        expected_version: int,
    ) -> Tenant | None:
        """Update active state when the expected version matches."""
        tenant = self._tenants_by_id.get(tenant_id)
        if tenant is None or tenant.version != expected_version:
            return None
        updated = replace(
            tenant,
            is_active=is_active,
            updated_at=utc_now(),
            version=tenant.version + 1,
        )
        self._tenants_by_id[tenant_id] = updated
        return updated
