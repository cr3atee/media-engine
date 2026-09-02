from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from app.api.schemas.common import ApiModel
from app.domain.marketplace_integrations import (
    MarketplaceAuthType,
    MarketplaceIntegrationStatus,
)


def _nonempty_text(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("Value must not be blank.")
    return normalized


def _optional_nonempty_text(value: str | None) -> str | None:
    if value is None:
        return None
    return _nonempty_text(value)


def _credential_reference(value: str) -> str:
    normalized = value.strip()
    if any(character.isspace() for character in normalized):
        raise ValueError("Credential reference must not contain whitespace.")
    return normalized


class MarketplaceCredentialResponse(ApiModel):
    """Credential metadata safe for seller API responses."""

    configured: bool
    auth_type: MarketplaceAuthType
    reference: str | None = None
    configured_at: datetime | None = None
    last_rotated_at: datetime | None = None
    version: int = Field(ge=0)


class MarketplaceIntegrationResponse(ApiModel):
    """Tenant-scoped marketplace integration response without secret values."""

    id: UUID
    tenant_id: UUID
    marketplace: str
    display_name: str
    enabled: bool
    status: MarketplaceIntegrationStatus
    external_account_id: str | None
    source_url: str | None
    auth_type: MarketplaceAuthType
    credential: MarketplaceCredentialResponse
    last_successful_run_at: datetime | None
    last_failed_run_at: datetime | None
    last_error_code: str | None
    last_error_summary: str | None
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=1)


class CreateMarketplaceIntegrationRequest(ApiModel):
    """Input for creating marketplace integration metadata."""

    marketplace: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    enabled: bool = False
    status: MarketplaceIntegrationStatus = MarketplaceIntegrationStatus.DRAFT
    external_account_id: str | None = Field(default=None, max_length=255)
    source_url: str | None = Field(default=None, max_length=2048)
    auth_type: MarketplaceAuthType = MarketplaceAuthType.NONE

    _normalize_marketplace = field_validator("marketplace")(_nonempty_text)
    _normalize_display_name = field_validator("display_name")(_nonempty_text)
    _normalize_external_account_id = field_validator("external_account_id")(
        _optional_nonempty_text
    )
    _normalize_source_url = field_validator("source_url")(_optional_nonempty_text)


class UpdateMarketplaceIntegrationRequest(ApiModel):
    """Input for an expected-version integration metadata update."""

    expected_version: int = Field(ge=1)
    display_name: str | None = Field(default=None, max_length=255)
    enabled: bool | None = None
    status: MarketplaceIntegrationStatus | None = None
    external_account_id: str | None = Field(default=None, max_length=255)
    source_url: str | None = Field(default=None, max_length=2048)
    auth_type: MarketplaceAuthType | None = None

    _normalize_display_name = field_validator("display_name")(_optional_nonempty_text)
    _normalize_external_account_id = field_validator("external_account_id")(
        _optional_nonempty_text
    )
    _normalize_source_url = field_validator("source_url")(_optional_nonempty_text)


class DisableMarketplaceIntegrationRequest(ApiModel):
    """Input for disabling one marketplace integration."""

    expected_version: int = Field(ge=1)


class RotateMarketplaceCredentialRequest(ApiModel):
    """Input for replacing an opaque marketplace credential reference."""

    expected_version: int = Field(ge=1)
    auth_type: MarketplaceAuthType
    credential_reference: str = Field(min_length=1, max_length=512)
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("auth_type")
    @classmethod
    def reject_none_auth_type(
        cls,
        value: MarketplaceAuthType,
    ) -> MarketplaceAuthType:
        """Credential rotation requires an authenticated integration mode."""
        if value is MarketplaceAuthType.NONE:
            raise ValueError("Credential rotation requires a non-none auth type.")
        return value

    _normalize_credential_reference = field_validator("credential_reference")(
        _credential_reference
    )
    _normalize_reason = field_validator("reason")(_optional_nonempty_text)
