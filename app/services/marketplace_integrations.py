from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID, uuid4

from app.domain.admin_actions import utc_now
from app.domain.marketplace_integrations import (
    CredentialRotationIntent,
    MarketplaceAuthType,
    MarketplaceCredentialMetadata,
    MarketplaceIntegration,
    MarketplaceIntegrationStatus,
    SafeMarketplaceIntegration,
    safe_marketplace_integration,
)
from app.repositories.base import RepositoryIdentityConflictError
from app.services.repository_scope import RepositoryScopeFactory

type Clock = Callable[[], datetime]
type IntegrationIdFactory = Callable[[], UUID]


@dataclass(slots=True, frozen=True, kw_only=True)
class CreateMarketplaceIntegrationCommand:
    """Input for creating one tenant-owned marketplace integration."""

    tenant_id: UUID
    marketplace: str
    display_name: str
    enabled: bool = False
    status: MarketplaceIntegrationStatus = MarketplaceIntegrationStatus.DRAFT
    external_account_id: str | None = None
    source_url: str | None = None
    auth_type: MarketplaceAuthType = MarketplaceAuthType.NONE


@dataclass(slots=True, frozen=True, kw_only=True)
class UpdateMarketplaceIntegrationCommand:
    """Expected-version metadata update for one marketplace integration."""

    tenant_id: UUID
    integration_id: UUID
    expected_version: int
    display_name: str | None = None
    enabled: bool | None = None
    status: MarketplaceIntegrationStatus | None = None
    external_account_id: str | None = None
    external_account_id_set: bool = False
    source_url: str | None = None
    source_url_set: bool = False
    auth_type: MarketplaceAuthType | None = None


@dataclass(slots=True, frozen=True, kw_only=True)
class DisableMarketplaceIntegrationCommand:
    """Expected-version command for disabling one integration."""

    tenant_id: UUID
    integration_id: UUID
    expected_version: int


@dataclass(slots=True, frozen=True, kw_only=True)
class RotateMarketplaceCredentialCommand:
    """Expected-version command for updating an opaque credential reference."""

    tenant_id: UUID
    integration_id: UUID
    expected_version: int
    auth_type: MarketplaceAuthType
    credential_reference: str
    actor_id: str
    reason: str | None = None


class MarketplaceIntegrationServiceError(Exception):
    """Safe marketplace integration failure with a stable API code."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = dict(details or {})
        super().__init__(message)


class MarketplaceIntegrationService:
    """Manage tenant-owned marketplace integrations without using credentials."""

    def __init__(
        self,
        repository_scope_factory: RepositoryScopeFactory,
        *,
        clock: Clock = utc_now,
        integration_id_factory: IntegrationIdFactory = uuid4,
    ) -> None:
        self._repository_scope_factory = repository_scope_factory
        self._clock = clock
        self._integration_id_factory = integration_id_factory

    async def list_tenant(
        self,
        tenant_id: UUID,
    ) -> Sequence[SafeMarketplaceIntegration]:
        """Return redacted marketplace integrations owned by one tenant."""
        async with self._repository_scope_factory() as repositories:
            integrations = await repositories.marketplace_integrations.list_by_tenant(
                tenant_id
            )
            return tuple(safe_marketplace_integration(item) for item in integrations)

    async def get(
        self,
        tenant_id: UUID,
        integration_id: UUID,
    ) -> SafeMarketplaceIntegration | None:
        """Return one redacted tenant-owned integration, if it exists."""
        async with self._repository_scope_factory() as repositories:
            integration = (
                await repositories.marketplace_integrations.get_by_tenant_and_id(
                    tenant_id,
                    integration_id,
                )
            )
            return (
                safe_marketplace_integration(integration)
                if integration is not None
                else None
            )

    async def create(
        self,
        command: CreateMarketplaceIntegrationCommand,
    ) -> SafeMarketplaceIntegration:
        """Create one tenant-owned integration metadata record."""
        now = self._clock()
        try:
            integration = MarketplaceIntegration(
                id=self._integration_id_factory(),
                tenant_id=command.tenant_id,
                marketplace=command.marketplace,
                display_name=command.display_name,
                enabled=command.enabled,
                status=command.status,
                external_account_id=command.external_account_id,
                source_url=command.source_url,
                auth_type=command.auth_type,
                created_at=now,
                updated_at=now,
            )
        except ValueError as exc:
            raise _service_error(
                "invalid_integration_payload",
                "Marketplace integration payload is invalid.",
                status_code=422,
            ) from exc
        async with self._repository_scope_factory() as repositories:
            try:
                stored = await repositories.marketplace_integrations.save(integration)
            except RepositoryIdentityConflictError as exc:
                raise _service_error(
                    "integration_identity_conflict",
                    "Marketplace integration identity already exists.",
                ) from exc
            return safe_marketplace_integration(stored)

    async def update(
        self,
        command: UpdateMarketplaceIntegrationCommand,
    ) -> SafeMarketplaceIntegration:
        """Update tenant-owned integration metadata using optimistic concurrency."""
        _validate_expected_version(command.expected_version)
        async with self._repository_scope_factory() as repositories:
            integration = (
                await repositories.marketplace_integrations.get_by_tenant_and_id(
                    command.tenant_id,
                    command.integration_id,
                )
            )
            _require_integration(integration)
            assert integration is not None
            _guard_expected_version(integration.version, command.expected_version)

            try:
                updated = _updated_integration(integration, command, self._clock())
            except ValueError as exc:
                raise _service_error(
                    "invalid_integration_payload",
                    "Marketplace integration payload is invalid.",
                    status_code=422,
                ) from exc
            try:
                stored = await repositories.marketplace_integrations.save(updated)
            except RepositoryIdentityConflictError as exc:
                raise _service_error(
                    "integration_identity_conflict",
                    "Marketplace integration identity already exists.",
                ) from exc
            return safe_marketplace_integration(stored)

    async def disable(
        self,
        command: DisableMarketplaceIntegrationCommand,
    ) -> SafeMarketplaceIntegration:
        """Disable one tenant-owned integration without deleting its metadata."""
        _validate_expected_version(command.expected_version)
        async with self._repository_scope_factory() as repositories:
            integration = (
                await repositories.marketplace_integrations.get_by_tenant_and_id(
                    command.tenant_id,
                    command.integration_id,
                )
            )
            _require_integration(integration)
            assert integration is not None
            _guard_expected_version(integration.version, command.expected_version)
            updated = replace(
                integration,
                enabled=False,
                status=MarketplaceIntegrationStatus.DISABLED,
                updated_at=self._clock(),
                version=integration.version + 1,
            )
            stored = await repositories.marketplace_integrations.save(updated)
            return safe_marketplace_integration(stored)

    async def rotate_credential(
        self,
        command: RotateMarketplaceCredentialCommand,
    ) -> SafeMarketplaceIntegration:
        """Attach an opaque credential reference and return only redacted metadata."""
        _validate_expected_version(command.expected_version)
        async with self._repository_scope_factory() as repositories:
            integration = (
                await repositories.marketplace_integrations.get_by_tenant_and_id(
                    command.tenant_id,
                    command.integration_id,
                )
            )
            _require_integration(integration)
            assert integration is not None
            _guard_expected_version(integration.version, command.expected_version)

            now = self._clock()
            previous_credential = integration.credential
            try:
                intent = CredentialRotationIntent(
                    tenant_id=command.tenant_id,
                    integration_id=command.integration_id,
                    auth_type=command.auth_type,
                    credential=MarketplaceCredentialMetadata(
                        reference=command.credential_reference,
                        configured_at=now,
                        last_rotated_at=now
                        if previous_credential is not None
                        else None,
                        version=(
                            previous_credential.version + 1
                            if previous_credential is not None
                            else 1
                        ),
                    ),
                    actor_id=command.actor_id,
                    requested_at=now,
                    expected_version=command.expected_version,
                    reason=command.reason,
                )
            except ValueError as exc:
                raise _service_error(
                    "invalid_credential_payload",
                    "Marketplace credential payload is invalid.",
                    status_code=422,
                ) from exc
            updated = (
                await repositories.marketplace_integrations.update_credential_reference(
                    intent
                )
            )
            if updated is None:
                raise _service_error(
                    "optimistic_concurrency_conflict",
                    "Resource version does not match the expected version.",
                    details={"current_version": integration.version},
                )
            return updated


def _updated_integration(
    integration: MarketplaceIntegration,
    command: UpdateMarketplaceIntegrationCommand,
    now: datetime,
) -> MarketplaceIntegration:
    return replace(
        integration,
        display_name=command.display_name
        if command.display_name is not None
        else integration.display_name,
        enabled=command.enabled if command.enabled is not None else integration.enabled,
        status=command.status if command.status is not None else integration.status,
        external_account_id=command.external_account_id
        if command.external_account_id_set
        else integration.external_account_id,
        source_url=command.source_url
        if command.source_url_set
        else integration.source_url,
        auth_type=command.auth_type
        if command.auth_type is not None
        else integration.auth_type,
        updated_at=now,
        version=integration.version + 1,
    )


def _validate_expected_version(expected_version: int) -> None:
    if expected_version < 1:
        raise _service_error(
            "invalid_expected_version",
            "Expected version must be positive.",
            status_code=422,
        )


def _guard_expected_version(current_version: int, expected_version: int) -> None:
    if current_version != expected_version:
        raise _service_error(
            "optimistic_concurrency_conflict",
            "Resource version does not match the expected version.",
            details={"current_version": current_version},
        )


def _require_integration(integration: MarketplaceIntegration | None) -> None:
    if integration is None:
        raise _service_error(
            "resource_not_found",
            "Marketplace integration was not found.",
            status_code=404,
        )


def _service_error(
    code: str,
    message: str,
    *,
    status_code: int = 409,
    details: Mapping[str, object] | None = None,
) -> MarketplaceIntegrationServiceError:
    return MarketplaceIntegrationServiceError(
        status_code,
        code,
        message,
        details=details,
    )
