from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.identity import normalize_utc


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

        object.__setattr__(self, "marketplace", marketplace)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)
        object.__setattr__(
            self,
            "status",
            MarketplaceIntegrationStatus(self.status),
        )
        object.__setattr__(self, "auth_type", MarketplaceAuthType(self.auth_type))
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
