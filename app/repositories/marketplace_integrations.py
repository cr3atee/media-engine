from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from uuid import UUID

from app.domain.marketplace_integrations import (
    CredentialRotationIntent,
    MarketplaceIntegration,
    SafeMarketplaceIntegration,
)
from app.repositories.base import BaseRepository


class MarketplaceIntegrationRepository(BaseRepository):
    """Abstract storage contract for tenant-owned marketplace integrations."""

    @abstractmethod
    async def save(
        self,
        integration: MarketplaceIntegration,
    ) -> MarketplaceIntegration:
        """Persist or update one integration metadata record."""

    @abstractmethod
    async def get_by_tenant_and_id(
        self,
        tenant_id: UUID,
        integration_id: UUID,
    ) -> MarketplaceIntegration | None:
        """Return one integration only when it belongs to the requested tenant."""

    @abstractmethod
    async def list_by_tenant(self, tenant_id: UUID) -> Sequence[MarketplaceIntegration]:
        """Return integrations owned by one tenant in deterministic order."""

    @abstractmethod
    async def list_enabled(self) -> Sequence[MarketplaceIntegration]:
        """Return all enabled active integrations for orchestration."""

    @abstractmethod
    async def list_enabled_by_tenant(
        self,
        tenant_id: UUID,
    ) -> Sequence[MarketplaceIntegration]:
        """Return enabled active integrations owned by one tenant."""

    @abstractmethod
    async def update_credential_reference(
        self,
        intent: CredentialRotationIntent,
    ) -> SafeMarketplaceIntegration | None:
        """Attach a credential reference and return only redacted metadata."""
