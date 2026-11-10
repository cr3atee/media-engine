from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from uuid import UUID

from app.catalog.hierarchy import CatalogSourceRule
from app.repositories.base import BaseRepository


class CatalogSourceRuleRepository(BaseRepository):
    """Storage contract for tenant- and integration-scoped catalog rules."""

    @abstractmethod
    async def save(self, rule: CatalogSourceRule) -> CatalogSourceRule:
        """Persist or update one verified source-category rule."""

    @abstractmethod
    async def get_by_source(
        self,
        tenant_id: UUID,
        integration_id: UUID,
        marketplace: str,
        source_category_id: str,
    ) -> CatalogSourceRule | None:
        """Return one rule only for the exact tenant integration source."""

    @abstractmethod
    async def list_by_integration(
        self,
        tenant_id: UUID,
        integration_id: UUID,
    ) -> Sequence[CatalogSourceRule]:
        """Return rules for one tenant integration in deterministic order."""

    @abstractmethod
    async def list_by_tenant(self, tenant_id: UUID) -> Sequence[CatalogSourceRule]:
        """Return all rules owned by one tenant in deterministic order."""
