from __future__ import annotations

from abc import abstractmethod
from uuid import UUID

from app.domain.tenancy import Tenant
from app.repositories.base import BaseRepository


class TenantRepository(BaseRepository):
    """Abstract storage contract for tenant/workspace identities."""

    @abstractmethod
    async def create(self, tenant: Tenant) -> Tenant:
        """Persist a new tenant."""

    @abstractmethod
    async def get_by_id(self, tenant_id: UUID) -> Tenant | None:
        """Return one tenant by technical identifier."""

    @abstractmethod
    async def get_by_slug(self, slug: str) -> Tenant | None:
        """Return one tenant by stable slug."""

    @abstractmethod
    async def get_legacy_tenant(self) -> Tenant | None:
        """Return the deterministic legacy tenant."""

    @abstractmethod
    async def set_active(
        self,
        tenant_id: UUID,
        is_active: bool,
        expected_version: int,
    ) -> Tenant | None:
        """Update active state using optimistic version guarding."""
