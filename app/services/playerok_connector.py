from __future__ import annotations

from app.core.http_client import HttpClient
from app.domain.marketplace_integrations import (
    MarketplaceAuthType,
    MarketplaceIntegration,
)
from app.parsers.models import ParsedOffer
from app.parsers.playerok_credentials import PlayerokSessionCredentials
from app.parsers.playerok_extractor import PlayerokExtractor
from app.parsers.playerok_fetcher import PlayerokFetcher
from app.parsers.playerok_normalizer import PlayerokNormalizer
from app.services.marketplace_credentials import MarketplaceCredentialResolver
from app.services.playerok_pipeline import PlayerokPipeline


class PlayerokConnectorConfigurationError(RuntimeError):
    """Safe failure for an incomplete Playerok integration configuration."""


class PlayerokConnector:
    """Build a Playerok ingestion pipeline from one tenant integration."""

    def __init__(
        self,
        *,
        http_client: HttpClient,
        integration: MarketplaceIntegration,
        credential_resolver: MarketplaceCredentialResolver | None,
    ) -> None:
        """Retain non-secret integration context until one execution starts."""
        self._http_client = http_client
        self._integration = integration
        self._credential_resolver = credential_resolver

    async def run(self, url: str) -> list[ParsedOffer]:
        """Resolve an optional session and run the existing Playerok pipeline."""
        session = await self._session_credentials()
        pipeline = PlayerokPipeline(
            fetcher=PlayerokFetcher(self._http_client, session=session),
            extractor=PlayerokExtractor(),
            normalizer=PlayerokNormalizer(),
        )
        return await pipeline.run(url)

    async def _session_credentials(self) -> PlayerokSessionCredentials | None:
        if self._integration.auth_type is MarketplaceAuthType.NONE:
            return None
        if self._integration.auth_type not in {
            MarketplaceAuthType.COOKIE,
            MarketplaceAuthType.SESSION,
        }:
            raise PlayerokConnectorConfigurationError(
                "Playerok integration authentication mode is unsupported."
            )
        if self._integration.credential is None:
            raise PlayerokConnectorConfigurationError(
                "Playerok integration credential is not configured."
            )
        if self._credential_resolver is None:
            raise PlayerokConnectorConfigurationError(
                "Playerok credential resolver is unavailable."
            )

        secret = await self._credential_resolver.resolve(
            tenant_id=self._integration.tenant_id,
            integration_id=self._integration.id,
            reference=self._integration.credential.reference,
        )
        return PlayerokSessionCredentials.from_secret(secret)
