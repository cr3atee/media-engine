from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.marketplace_integrations import (
    CredentialRotationIntent,
    MarketplaceAuthType,
    MarketplaceCredentialMetadata,
    MarketplaceIntegration,
    MarketplaceIntegrationStatus,
    SafeMarketplaceIntegration,
    safe_marketplace_integration,
)
from app.models.marketplace_integration_record import MarketplaceIntegrationRecord
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.marketplace_integrations import (
    MarketplaceIntegrationRepository,
)


class PostgresMarketplaceIntegrationRepository(MarketplaceIntegrationRepository):
    """PostgreSQL repository for tenant-owned marketplace integrations."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a caller-owned session and transaction."""
        self._session = session

    async def save(
        self,
        integration: MarketplaceIntegration,
    ) -> MarketplaceIntegration:
        """Persist or update one integration metadata record."""
        existing = await self._session.get(MarketplaceIntegrationRecord, integration.id)
        if existing is not None and existing.tenant_id != integration.tenant_id:
            msg = f"Marketplace integration ID already exists: {integration.id}."
            raise RepositoryIdentityConflictError(msg)

        await self._ensure_unique_identity(integration)
        if existing is None:
            self._session.add(_to_record(integration))
        else:
            _update_record(existing, integration)
        await self._session.flush()
        return integration

    async def get_by_tenant_and_id(
        self,
        tenant_id: UUID,
        integration_id: UUID,
    ) -> MarketplaceIntegration | None:
        """Return one integration only when it belongs to the requested tenant."""
        result = await self._session.execute(
            select(MarketplaceIntegrationRecord).where(
                MarketplaceIntegrationRecord.tenant_id == tenant_id,
                MarketplaceIntegrationRecord.id == integration_id,
            )
        )
        record = result.scalar_one_or_none()
        return _to_domain(record) if record is not None else None

    async def list_by_tenant(self, tenant_id: UUID) -> Sequence[MarketplaceIntegration]:
        """Return integrations owned by one tenant in deterministic order."""
        result = await self._session.execute(
            select(MarketplaceIntegrationRecord)
            .where(MarketplaceIntegrationRecord.tenant_id == tenant_id)
            .order_by(
                MarketplaceIntegrationRecord.created_at,
                MarketplaceIntegrationRecord.id,
            )
        )
        return tuple(_to_domain(record) for record in result.scalars())

    async def list_enabled(self) -> Sequence[MarketplaceIntegration]:
        """Return all enabled active integrations for orchestration."""
        result = await self._session.execute(
            _enabled_query().order_by(
                MarketplaceIntegrationRecord.created_at,
                MarketplaceIntegrationRecord.id,
            )
        )
        return tuple(_to_domain(record) for record in result.scalars())

    async def list_enabled_by_tenant(
        self,
        tenant_id: UUID,
    ) -> Sequence[MarketplaceIntegration]:
        """Return enabled active integrations owned by one tenant."""
        result = await self._session.execute(
            _enabled_query()
            .where(MarketplaceIntegrationRecord.tenant_id == tenant_id)
            .order_by(
                MarketplaceIntegrationRecord.created_at,
                MarketplaceIntegrationRecord.id,
            )
        )
        return tuple(_to_domain(record) for record in result.scalars())

    async def update_credential_reference(
        self,
        intent: CredentialRotationIntent,
    ) -> SafeMarketplaceIntegration | None:
        """Attach a credential reference and return a redacted integration view."""
        result = await self._session.execute(
            select(MarketplaceIntegrationRecord)
            .where(
                MarketplaceIntegrationRecord.id == intent.integration_id,
                MarketplaceIntegrationRecord.tenant_id == intent.tenant_id,
            )
            .with_for_update()
        )
        record = result.scalar_one_or_none()
        if record is None or record.version != intent.expected_version:
            return None

        record.auth_type = intent.auth_type.value
        record.credential_reference = intent.credential.reference
        record.credential_configured_at = intent.credential.configured_at
        record.credential_last_rotated_at = intent.credential.last_rotated_at
        record.credential_version = intent.credential.version
        record.updated_at = intent.requested_at
        record.version += 1
        await self._session.flush()
        return safe_marketplace_integration(_to_domain(record))

    async def _ensure_unique_identity(
        self,
        integration: MarketplaceIntegration,
    ) -> None:
        if integration.external_account_id is not None:
            conflict = await self._find_external_account_conflict(integration)
            if conflict is not None:
                msg = (
                    "Marketplace integration external account identity already "
                    f"exists for tenant: {integration.external_account_id}."
                )
                raise RepositoryIdentityConflictError(msg)
        if integration.source_url is not None:
            conflict = await self._find_source_url_conflict(integration)
            if conflict is not None:
                msg = (
                    "Marketplace integration source URL identity already exists "
                    f"for tenant: {integration.source_url}."
                )
                raise RepositoryIdentityConflictError(msg)

    async def _find_external_account_conflict(
        self,
        integration: MarketplaceIntegration,
    ) -> UUID | None:
        result = await self._session.execute(
            select(MarketplaceIntegrationRecord.id)
            .where(
                MarketplaceIntegrationRecord.tenant_id == integration.tenant_id,
                MarketplaceIntegrationRecord.marketplace == integration.marketplace,
                MarketplaceIntegrationRecord.external_account_id
                == integration.external_account_id,
                MarketplaceIntegrationRecord.id != integration.id,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _find_source_url_conflict(
        self,
        integration: MarketplaceIntegration,
    ) -> UUID | None:
        result = await self._session.execute(
            select(MarketplaceIntegrationRecord.id)
            .where(
                MarketplaceIntegrationRecord.tenant_id == integration.tenant_id,
                MarketplaceIntegrationRecord.marketplace == integration.marketplace,
                MarketplaceIntegrationRecord.source_url == integration.source_url,
                MarketplaceIntegrationRecord.id != integration.id,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()


def _enabled_query() -> Select[tuple[MarketplaceIntegrationRecord]]:
    return select(MarketplaceIntegrationRecord).where(
        MarketplaceIntegrationRecord.enabled.is_(True),
        MarketplaceIntegrationRecord.status
        == MarketplaceIntegrationStatus.ACTIVE.value,
    )


def _to_record(integration: MarketplaceIntegration) -> MarketplaceIntegrationRecord:
    credential = integration.credential
    return MarketplaceIntegrationRecord(
        id=integration.id,
        tenant_id=integration.tenant_id,
        marketplace=integration.marketplace,
        display_name=integration.display_name,
        enabled=integration.enabled,
        status=integration.status.value,
        external_account_id=integration.external_account_id,
        source_url=integration.source_url,
        auth_type=integration.auth_type.value,
        credential_reference=credential.reference if credential is not None else None,
        credential_configured_at=credential.configured_at
        if credential is not None
        else None,
        credential_last_rotated_at=credential.last_rotated_at
        if credential is not None
        else None,
        credential_version=credential.version if credential is not None else 0,
        last_successful_run_at=integration.last_successful_run_at,
        last_failed_run_at=integration.last_failed_run_at,
        last_error_code=integration.last_error_code,
        last_error_summary=integration.last_error_summary,
        created_at=integration.created_at,
        updated_at=integration.updated_at,
        version=integration.version,
    )


def _update_record(
    record: MarketplaceIntegrationRecord,
    integration: MarketplaceIntegration,
) -> None:
    credential = integration.credential
    record.marketplace = integration.marketplace
    record.display_name = integration.display_name
    record.enabled = integration.enabled
    record.status = integration.status.value
    record.external_account_id = integration.external_account_id
    record.source_url = integration.source_url
    record.auth_type = integration.auth_type.value
    record.credential_reference = (
        credential.reference if credential is not None else None
    )
    record.credential_configured_at = (
        credential.configured_at if credential is not None else None
    )
    record.credential_last_rotated_at = (
        credential.last_rotated_at if credential is not None else None
    )
    record.credential_version = credential.version if credential is not None else 0
    record.last_successful_run_at = integration.last_successful_run_at
    record.last_failed_run_at = integration.last_failed_run_at
    record.last_error_code = integration.last_error_code
    record.last_error_summary = integration.last_error_summary
    record.updated_at = integration.updated_at
    record.version = integration.version


def _to_domain(record: MarketplaceIntegrationRecord) -> MarketplaceIntegration:
    return MarketplaceIntegration(
        id=record.id,
        tenant_id=record.tenant_id,
        marketplace=record.marketplace,
        display_name=record.display_name,
        enabled=record.enabled,
        status=MarketplaceIntegrationStatus(record.status),
        external_account_id=record.external_account_id,
        source_url=record.source_url,
        auth_type=MarketplaceAuthType(record.auth_type),
        credential=_to_credential_metadata(record),
        last_successful_run_at=record.last_successful_run_at,
        last_failed_run_at=record.last_failed_run_at,
        last_error_code=record.last_error_code,
        last_error_summary=record.last_error_summary,
        created_at=record.created_at,
        updated_at=record.updated_at,
        version=record.version,
    )


def _to_credential_metadata(
    record: MarketplaceIntegrationRecord,
) -> MarketplaceCredentialMetadata | None:
    if record.credential_reference is None:
        return None
    configured_at = record.credential_configured_at
    if configured_at is None:
        msg = "Credential metadata is missing configuration timestamp."
        raise RuntimeError(msg)
    return MarketplaceCredentialMetadata(
        reference=record.credential_reference,
        configured_at=configured_at,
        last_rotated_at=record.credential_last_rotated_at,
        version=record.credential_version,
    )
