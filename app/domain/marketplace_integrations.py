from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.identity import normalize_utc

type AuditMetadataValue = bool | int | str | None
REDACTED_CREDENTIAL_REFERENCE = "[redacted]"


class MarketplaceIntegrationStatus(StrEnum):
    """Operational state of one tenant-owned marketplace integration."""

    DRAFT = "draft"
    ACTIVE = "active"
    DISABLED = "disabled"
    ERROR = "error"


class MarketplaceAuthType(StrEnum):
    """Credential mode declared by a marketplace integration."""

    NONE = "none"
    API_KEY = "api_key"
    COOKIE = "cookie"
    SESSION = "session"


@dataclass(slots=True, frozen=True, kw_only=True)
class MarketplaceCredentialMetadata:
    """Opaque credential reference metadata without plaintext secret material."""

    reference: str
    configured_at: datetime
    last_rotated_at: datetime | None = None
    version: int = 1

    def __post_init__(self) -> None:
        reference = _require_token(
            self.reference,
            field_name="credential_reference",
            maximum_length=512,
        )
        configured_at = normalize_utc(
            self.configured_at,
            field_name="credential_configured_at",
        )
        last_rotated_at = _optional_utc(
            self.last_rotated_at,
            field_name="credential_last_rotated_at",
        )
        if last_rotated_at is not None and last_rotated_at < configured_at:
            msg = "Credential rotation time must not predate configuration time."
            raise ValueError(msg)
        if self.version < 1:
            msg = "Credential metadata version must be positive."
            raise ValueError(msg)
        object.__setattr__(self, "reference", reference)
        object.__setattr__(self, "configured_at", configured_at)
        object.__setattr__(self, "last_rotated_at", last_rotated_at)


@dataclass(slots=True, frozen=True, kw_only=True)
class RedactedCredentialMetadata:
    """Credential metadata safe for API responses, logs, and audit output."""

    configured: bool
    auth_type: MarketplaceAuthType
    reference: str | None = None
    configured_at: datetime | None = None
    last_rotated_at: datetime | None = None
    version: int = 0


@dataclass(slots=True, frozen=True, kw_only=True)
class SafeMarketplaceIntegration:
    """Marketplace integration view that never exposes credential references."""

    id: UUID
    tenant_id: UUID
    marketplace: str
    display_name: str
    enabled: bool
    status: MarketplaceIntegrationStatus
    external_account_id: str | None
    source_url: str | None
    auth_type: MarketplaceAuthType
    credential: RedactedCredentialMetadata
    last_successful_run_at: datetime | None
    last_failed_run_at: datetime | None
    last_error_code: str | None
    last_error_summary: str | None
    created_at: datetime
    updated_at: datetime
    version: int


@dataclass(slots=True, frozen=True, kw_only=True)
class CredentialRotationIntent:
    """Audit-safe intent to attach a credential reference to an integration."""

    tenant_id: UUID
    integration_id: UUID
    auth_type: MarketplaceAuthType
    credential: MarketplaceCredentialMetadata
    actor_id: str
    requested_at: datetime
    expected_version: int
    reason: str | None = None

    def __post_init__(self) -> None:
        auth_type = MarketplaceAuthType(self.auth_type)
        if auth_type is MarketplaceAuthType.NONE:
            msg = "Credential rotation requires an authenticated marketplace mode."
            raise ValueError(msg)
        if self.expected_version < 1:
            msg = "Expected integration version must be positive."
            raise ValueError(msg)
        object.__setattr__(self, "auth_type", auth_type)
        object.__setattr__(
            self,
            "actor_id",
            _require_text(self.actor_id, field_name="actor_id", maximum_length=128),
        )
        object.__setattr__(
            self,
            "requested_at",
            normalize_utc(self.requested_at, field_name="requested_at"),
        )
        object.__setattr__(
            self,
            "reason",
            _optional_text(self.reason, field_name="reason", maximum_length=500),
        )

    def audit_metadata(self) -> dict[str, AuditMetadataValue]:
        """Return redacted metadata safe for immutable audit records."""
        return {
            "auth_type": self.auth_type.value,
            "credential_configured": True,
            "credential_reference": REDACTED_CREDENTIAL_REFERENCE,
            "credential_version": self.credential.version,
            "reason": self.reason,
        }


@dataclass(slots=True, frozen=True, kw_only=True)
class MarketplaceIntegration:
    """Tenant-owned marketplace data-source configuration without secrets."""

    id: UUID
    tenant_id: UUID
    marketplace: str
    display_name: str
    created_at: datetime
    updated_at: datetime
    enabled: bool = False
    status: MarketplaceIntegrationStatus = MarketplaceIntegrationStatus.DRAFT
    external_account_id: str | None = None
    source_url: str | None = None
    auth_type: MarketplaceAuthType = MarketplaceAuthType.NONE
    credential: MarketplaceCredentialMetadata | None = None
    last_successful_run_at: datetime | None = None
    last_failed_run_at: datetime | None = None
    last_error_code: str | None = None
    last_error_summary: str | None = None
    version: int = 1

    def __post_init__(self) -> None:
        marketplace = _require_text(
            self.marketplace,
            field_name="marketplace",
            maximum_length=64,
        ).lower()
        display_name = _require_text(
            self.display_name,
            field_name="display_name",
            maximum_length=255,
        )
        created_at = normalize_utc(self.created_at, field_name="created_at")
        updated_at = normalize_utc(self.updated_at, field_name="updated_at")
        if updated_at < created_at:
            msg = "Marketplace integration update time must not predate creation time."
            raise ValueError(msg)
        if self.version < 1:
            msg = "Marketplace integration version must be positive."
            raise ValueError(msg)
        status = MarketplaceIntegrationStatus(self.status)
        auth_type = MarketplaceAuthType(self.auth_type)
        if auth_type is MarketplaceAuthType.NONE and self.credential is not None:
            msg = "Credential metadata requires a non-none auth type."
            raise ValueError(msg)

        object.__setattr__(self, "marketplace", marketplace)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "auth_type", auth_type)
        object.__setattr__(
            self,
            "external_account_id",
            _optional_text(
                self.external_account_id,
                field_name="external_account_id",
                maximum_length=255,
            ),
        )
        object.__setattr__(
            self,
            "source_url",
            _optional_text(
                self.source_url,
                field_name="source_url",
                maximum_length=2048,
            ),
        )
        object.__setattr__(
            self,
            "last_error_code",
            _optional_text(
                self.last_error_code,
                field_name="last_error_code",
                maximum_length=128,
            ),
        )
        object.__setattr__(
            self,
            "last_error_summary",
            _optional_text(
                self.last_error_summary,
                field_name="last_error_summary",
                maximum_length=2000,
            ),
        )
        object.__setattr__(
            self,
            "last_successful_run_at",
            _optional_utc(
                self.last_successful_run_at,
                field_name="last_successful_run_at",
            ),
        )
        object.__setattr__(
            self,
            "last_failed_run_at",
            _optional_utc(self.last_failed_run_at, field_name="last_failed_run_at"),
        )


def redact_credential_reference(reference: str | None) -> str | None:
    """Return a constant redaction marker for any configured reference."""
    if reference is None:
        return None
    return REDACTED_CREDENTIAL_REFERENCE


def redacted_credential_metadata(
    integration: MarketplaceIntegration,
) -> RedactedCredentialMetadata:
    """Build a credential metadata DTO safe for external boundaries."""
    credential = integration.credential
    if credential is None:
        return RedactedCredentialMetadata(
            configured=False,
            auth_type=integration.auth_type,
        )
    return RedactedCredentialMetadata(
        configured=True,
        auth_type=integration.auth_type,
        reference=redact_credential_reference(credential.reference),
        configured_at=credential.configured_at,
        last_rotated_at=credential.last_rotated_at,
        version=credential.version,
    )


def safe_marketplace_integration(
    integration: MarketplaceIntegration,
) -> SafeMarketplaceIntegration:
    """Build a marketplace integration DTO without credential references."""
    return SafeMarketplaceIntegration(
        id=integration.id,
        tenant_id=integration.tenant_id,
        marketplace=integration.marketplace,
        display_name=integration.display_name,
        enabled=integration.enabled,
        status=integration.status,
        external_account_id=integration.external_account_id,
        source_url=integration.source_url,
        auth_type=integration.auth_type,
        credential=redacted_credential_metadata(integration),
        last_successful_run_at=integration.last_successful_run_at,
        last_failed_run_at=integration.last_failed_run_at,
        last_error_code=integration.last_error_code,
        last_error_summary=integration.last_error_summary,
        created_at=integration.created_at,
        updated_at=integration.updated_at,
        version=integration.version,
    )


def _optional_utc(value: datetime | None, *, field_name: str) -> datetime | None:
    if value is None:
        return None
    return normalize_utc(value, field_name=field_name)


def _optional_text(
    value: str | None,
    *,
    field_name: str,
    maximum_length: int,
) -> str | None:
    if value is None:
        return None
    return _require_text(value, field_name=field_name, maximum_length=maximum_length)


def _require_text(value: str, *, field_name: str, maximum_length: int) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        msg = f"{field_name} must not be empty."
        raise ValueError(msg)
    if len(normalized) > maximum_length:
        msg = f"{field_name} must not exceed {maximum_length} characters."
        raise ValueError(msg)
    return normalized


def _require_token(value: str, *, field_name: str, maximum_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        msg = f"{field_name} must not be empty."
        raise ValueError(msg)
    if any(character.isspace() for character in normalized):
        msg = f"{field_name} must not contain whitespace."
        raise ValueError(msg)
    if len(normalized) > maximum_length:
        msg = f"{field_name} must not exceed {maximum_length} characters."
        raise ValueError(msg)
    return normalized
