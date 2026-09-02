from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies import (
    get_marketplace_integration_service,
    require_tenant_permission,
)
from app.api.errors import ApiError
from app.api.schemas.marketplace_integrations import (
    CreateMarketplaceIntegrationRequest,
    DisableMarketplaceIntegrationRequest,
    MarketplaceCredentialResponse,
    MarketplaceIntegrationResponse,
    RotateMarketplaceCredentialRequest,
    UpdateMarketplaceIntegrationRequest,
)
from app.domain.auth import Permission, TenantContext
from app.domain.marketplace_integrations import (
    RedactedCredentialMetadata,
    SafeMarketplaceIntegration,
)
from app.services.marketplace_integrations import (
    CreateMarketplaceIntegrationCommand,
    DisableMarketplaceIntegrationCommand,
    MarketplaceIntegrationService,
    MarketplaceIntegrationServiceError,
    RotateMarketplaceCredentialCommand,
    UpdateMarketplaceIntegrationCommand,
)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/marketplace-integrations",
    tags=["Seller marketplace integrations"],
)

IntegrationReadTenant = Annotated[
    TenantContext,
    Depends(require_tenant_permission(Permission.INTEGRATIONS_READ)),
]
IntegrationManageTenant = Annotated[
    TenantContext,
    Depends(require_tenant_permission(Permission.INTEGRATION_MANAGE)),
]


@router.get("", response_model=list[MarketplaceIntegrationResponse])
async def list_marketplace_integrations(
    context: IntegrationReadTenant,
    service: Annotated[
        MarketplaceIntegrationService,
        Depends(get_marketplace_integration_service),
    ],
) -> list[MarketplaceIntegrationResponse]:
    """List tenant-owned marketplace integrations without credential exposure."""
    integrations = await service.list_tenant(context.tenant.id)
    return [_response(integration) for integration in integrations]


@router.get("/{integration_id}", response_model=MarketplaceIntegrationResponse)
async def get_marketplace_integration(
    integration_id: UUID,
    context: IntegrationReadTenant,
    service: Annotated[
        MarketplaceIntegrationService,
        Depends(get_marketplace_integration_service),
    ],
) -> MarketplaceIntegrationResponse:
    """Return one tenant-owned marketplace integration."""
    integration = await service.get(context.tenant.id, integration_id)
    if integration is None:
        raise ApiError(
            404,
            "resource_not_found",
            "Marketplace integration was not found.",
        )
    return _response(integration)


@router.post(
    "",
    response_model=MarketplaceIntegrationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_marketplace_integration(
    payload: CreateMarketplaceIntegrationRequest,
    context: IntegrationManageTenant,
    service: Annotated[
        MarketplaceIntegrationService,
        Depends(get_marketplace_integration_service),
    ],
) -> MarketplaceIntegrationResponse:
    """Create tenant-owned marketplace integration metadata."""
    try:
        integration = await service.create(
            CreateMarketplaceIntegrationCommand(
                tenant_id=context.tenant.id,
                marketplace=payload.marketplace,
                display_name=payload.display_name,
                enabled=payload.enabled,
                status=payload.status,
                external_account_id=payload.external_account_id,
                source_url=payload.source_url,
                auth_type=payload.auth_type,
            )
        )
    except MarketplaceIntegrationServiceError as exc:
        raise _api_error(exc) from exc
    return _response(integration)


@router.post("/{integration_id}/update", response_model=MarketplaceIntegrationResponse)
async def update_marketplace_integration(
    integration_id: UUID,
    payload: UpdateMarketplaceIntegrationRequest,
    context: IntegrationManageTenant,
    service: Annotated[
        MarketplaceIntegrationService,
        Depends(get_marketplace_integration_service),
    ],
) -> MarketplaceIntegrationResponse:
    """Update tenant-owned marketplace integration metadata."""
    try:
        integration = await service.update(
            UpdateMarketplaceIntegrationCommand(
                tenant_id=context.tenant.id,
                integration_id=integration_id,
                expected_version=payload.expected_version,
                display_name=payload.display_name,
                enabled=payload.enabled,
                status=payload.status,
                external_account_id=payload.external_account_id,
                external_account_id_set=(
                    "external_account_id" in payload.model_fields_set
                ),
                source_url=payload.source_url,
                source_url_set="source_url" in payload.model_fields_set,
                auth_type=payload.auth_type,
            )
        )
    except MarketplaceIntegrationServiceError as exc:
        raise _api_error(exc) from exc
    return _response(integration)


@router.post(
    "/{integration_id}/disable",
    response_model=MarketplaceIntegrationResponse,
)
async def disable_marketplace_integration(
    integration_id: UUID,
    payload: DisableMarketplaceIntegrationRequest,
    context: IntegrationManageTenant,
    service: Annotated[
        MarketplaceIntegrationService,
        Depends(get_marketplace_integration_service),
    ],
) -> MarketplaceIntegrationResponse:
    """Disable one tenant-owned marketplace integration."""
    try:
        integration = await service.disable(
            DisableMarketplaceIntegrationCommand(
                tenant_id=context.tenant.id,
                integration_id=integration_id,
                expected_version=payload.expected_version,
            )
        )
    except MarketplaceIntegrationServiceError as exc:
        raise _api_error(exc) from exc
    return _response(integration)


@router.post(
    "/{integration_id}/credentials/rotate",
    response_model=MarketplaceIntegrationResponse,
)
async def rotate_marketplace_credential(
    integration_id: UUID,
    payload: RotateMarketplaceCredentialRequest,
    context: IntegrationManageTenant,
    service: Annotated[
        MarketplaceIntegrationService,
        Depends(get_marketplace_integration_service),
    ],
) -> MarketplaceIntegrationResponse:
    """Attach an opaque credential reference and return only redacted metadata."""
    try:
        integration = await service.rotate_credential(
            RotateMarketplaceCredentialCommand(
                tenant_id=context.tenant.id,
                integration_id=integration_id,
                expected_version=payload.expected_version,
                auth_type=payload.auth_type,
                credential_reference=payload.credential_reference,
                actor_id=str(context.principal.user_id),
                reason=payload.reason,
            )
        )
    except MarketplaceIntegrationServiceError as exc:
        raise _api_error(exc) from exc
    return _response(integration)


def _api_error(error: MarketplaceIntegrationServiceError) -> ApiError:
    return ApiError(
        error.status_code,
        error.code,
        error.message,
        details=error.details,
    )


def _response(
    integration: SafeMarketplaceIntegration,
) -> MarketplaceIntegrationResponse:
    return MarketplaceIntegrationResponse(
        id=integration.id,
        tenant_id=integration.tenant_id,
        marketplace=integration.marketplace,
        display_name=integration.display_name,
        enabled=integration.enabled,
        status=integration.status,
        external_account_id=integration.external_account_id,
        source_url=integration.source_url,
        auth_type=integration.auth_type,
        credential=_credential_response(integration.credential),
        last_successful_run_at=integration.last_successful_run_at,
        last_failed_run_at=integration.last_failed_run_at,
        last_error_code=integration.last_error_code,
        last_error_summary=integration.last_error_summary,
        created_at=integration.created_at,
        updated_at=integration.updated_at,
        version=integration.version,
    )


def _credential_response(
    credential: RedactedCredentialMetadata,
) -> MarketplaceCredentialResponse:
    return MarketplaceCredentialResponse(
        configured=credential.configured,
        auth_type=credential.auth_type,
        reference=credential.reference,
        configured_at=credential.configured_at,
        last_rotated_at=credential.last_rotated_at,
        version=credential.version,
    )
