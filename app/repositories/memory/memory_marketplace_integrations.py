from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from uuid import UUID

from app.domain.marketplace_integrations import (
    CredentialRotationIntent,
    MarketplaceIntegration,
    MarketplaceIntegrationStatus,
    SafeMarketplaceIntegration,
    safe_marketplace_integration,
)
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.marketplace_integrations import (
    MarketplaceIntegrationRepository,
)


class MemoryMarketplaceIntegrationRepository(MarketplaceIntegrationRepository):
    """Deterministic in-memory repository for marketplace integrations."""

    def __init__(self) -> None:
        """Initialize isolated integration storage."""
        self._integrations_by_id: dict[UUID, MarketplaceIntegration] = {}
        self._order: list[UUID] = []

    async def save(
        self,
        integration: MarketplaceIntegration,
    ) -> MarketplaceIntegration:
        """Persist or update one integration while preserving insertion order."""
        existing = self._integrations_by_id.get(integration.id)
        if existing is not None and existing.tenant_id != integration.tenant_id:
            msg = f"Marketplace integration ID already exists: {integration.id}."
            raise RepositoryIdentityConflictError(msg)

        self._ensure_unique_identity(integration)
        if existing is None:
            self._order.append(integration.id)
        self._integrations_by_id[integration.id] = integration
        return integration

    async def get_by_tenant_and_id(
        self,
        tenant_id: UUID,
        integration_id: UUID,
    ) -> MarketplaceIntegration | None:
        """Return one integration when it belongs to the requested tenant."""
        integration = self._integrations_by_id.get(integration_id)
        if integration is None or integration.tenant_id != tenant_id:
            return None
        return integration

    async def list_by_tenant(self, tenant_id: UUID) -> Sequence[MarketplaceIntegration]:
        """Return integrations owned by one tenant in insertion order."""
        return tuple(
            integration
            for integration in self._iter_ordered()
            if integration.tenant_id == tenant_id
        )

    async def list_enabled(self) -> Sequence[MarketplaceIntegration]:
        """Return all enabled active integrations in insertion order."""
        return tuple(
            integration
            for integration in self._iter_ordered()
            if _is_enabled_active(integration)
        )

    async def list_enabled_by_tenant(
        self,
        tenant_id: UUID,
    ) -> Sequence[MarketplaceIntegration]:
        """Return enabled active integrations owned by one tenant."""
        return tuple(
            integration
            for integration in self._iter_ordered()
            if integration.tenant_id == tenant_id and _is_enabled_active(integration)
        )

    async def update_credential_reference(
        self,
        intent: CredentialRotationIntent,
    ) -> SafeMarketplaceIntegration | None:
        """Attach a credential reference and return a redacted integration view."""
        integration = self._integrations_by_id.get(intent.integration_id)
        if integration is None or integration.tenant_id != intent.tenant_id:
            return None
        if integration.version != intent.expected_version:
            return None

        updated = replace(
            integration,
            auth_type=intent.auth_type,
            credential=intent.credential,
            updated_at=intent.requested_at,
            version=integration.version + 1,
        )
        self._ensure_unique_identity(updated)
        self._integrations_by_id[updated.id] = updated
        return safe_marketplace_integration(updated)

    def _iter_ordered(self) -> tuple[MarketplaceIntegration, ...]:
        return tuple(
            self._integrations_by_id[integration_id] for integration_id in self._order
        )

    def _ensure_unique_identity(self, integration: MarketplaceIntegration) -> None:
        for stored in self._integrations_by_id.values():
            if stored.id == integration.id:
                continue
            if _same_external_account_identity(stored, integration):
                msg = (
                    "Marketplace integration external account identity already "
                    f"exists for tenant: {integration.external_account_id}."
                )
                raise RepositoryIdentityConflictError(msg)
            if _same_source_url_identity(stored, integration):
                msg = (
                    "Marketplace integration source URL identity already exists "
                    f"for tenant: {integration.source_url}."
                )
                raise RepositoryIdentityConflictError(msg)


def _is_enabled_active(integration: MarketplaceIntegration) -> bool:
    return (
        integration.enabled
        and integration.status is MarketplaceIntegrationStatus.ACTIVE
    )


def _same_external_account_identity(
    left: MarketplaceIntegration,
    right: MarketplaceIntegration,
) -> bool:
    return (
        left.tenant_id == right.tenant_id
        and left.marketplace == right.marketplace
        and left.external_account_id is not None
        and left.external_account_id == right.external_account_id
    )


def _same_source_url_identity(
    left: MarketplaceIntegration,
    right: MarketplaceIntegration,
) -> bool:
    return (
        left.tenant_id == right.tenant_id
        and left.marketplace == right.marketplace
        and left.source_url is not None
        and left.source_url == right.source_url
    )
