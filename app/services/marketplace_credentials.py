from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Protocol
from uuid import UUID

from pydantic import SecretStr


class MarketplaceCredentialResolutionError(RuntimeError):
    """Safe failure raised when an opaque marketplace secret cannot be resolved."""


class MarketplaceCredentialResolver(Protocol):
    """Resolve tenant-scoped marketplace credentials outside persistence."""

    async def resolve(
        self,
        *,
        tenant_id: UUID,
        integration_id: UUID,
        reference: str,
    ) -> SecretStr:
        """Return secret material for one tenant-owned integration reference."""


class EnvironmentMarketplaceCredentialResolver:
    """Resolve allowlisted ``env://`` references from deployment secrets."""

    REFERENCE_PREFIX = "env://"
    ENVIRONMENT_PREFIX = "MEDIAENGINE_MARKETPLACE_SECRET_"
    _REFERENCE_NAME = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")

    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        """Use the process environment unless an explicit mapping is supplied."""
        self._environment = os.environ if environment is None else environment

    async def resolve(
        self,
        *,
        tenant_id: UUID,
        integration_id: UUID,
        reference: str,
    ) -> SecretStr:
        """Resolve one safe environment reference without exposing its value."""
        name = self._reference_name(reference)
        variable_name = (
            f"{self.ENVIRONMENT_PREFIX}{tenant_id.hex.upper()}_"
            f"{integration_id.hex.upper()}_{name}"
        )
        secret = self._environment.get(variable_name, "")
        if not secret.strip():
            raise MarketplaceCredentialResolutionError(
                "Marketplace credential secret is unavailable."
            )
        return SecretStr(secret)

    def _reference_name(self, reference: str) -> str:
        if not reference.startswith(self.REFERENCE_PREFIX):
            raise MarketplaceCredentialResolutionError(
                "Marketplace credential reference scheme is unsupported."
            )
        name = reference.removeprefix(self.REFERENCE_PREFIX)
        if self._REFERENCE_NAME.fullmatch(name) is None:
            raise MarketplaceCredentialResolutionError(
                "Marketplace credential reference is invalid."
            )
        return name
