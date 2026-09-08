from __future__ import annotations

from collections.abc import Mapping

from app.analytics.price_change import PriceChangeDetector
from app.core.http_client import HttpClient
from app.domain.marketplace import Marketplace
from app.domain.marketplace_integrations import MarketplaceIntegration
from app.insights.scoring import EventScorer
from app.parsers.funpay_extractor import FunPayExtractor
from app.parsers.funpay_fetcher import FunPayFetcher
from app.parsers.funpay_normalizer import FunPayNormalizer
from app.parsers.ggsel_extractor import GGSelExtractor
from app.parsers.ggsel_fetcher import GGSelFetcher
from app.parsers.normalizers import OfferNormalizer
from app.parsers.playerok_extractor import PlayerokExtractor
from app.parsers.playerok_fetcher import PlayerokFetcher
from app.parsers.playerok_normalizer import PlayerokNormalizer
from app.services.event_builder import EventBuilder
from app.services.funpay_pipeline import FunPayPipeline
from app.services.marketplace_application_runner import MarketplaceApplicationRunner
from app.services.marketplace_integration_execution import (
    MarketplaceIntegrationRunnerFactory,
)
from app.services.marketplace_pipeline import MarketplacePipeline, StageReporter
from app.services.playerok_pipeline import PlayerokPipeline
from app.services.repository_scope import RepositoryScopeFactory
from app.services.snapshot_builder import SnapshotBuilder


def create_marketplace_processing_pipeline(
    http_client: HttpClient,
    *,
    stage_reporter: StageReporter | None = None,
) -> MarketplacePipeline:
    """Create the shared offer-to-event processing pipeline."""
    return MarketplacePipeline(
        fetcher=GGSelFetcher(http_client),
        extractor=GGSelExtractor(),
        normalizer=OfferNormalizer(Marketplace.GGSEL.value),
        snapshot_builder=SnapshotBuilder(),
        price_change_detector=PriceChangeDetector(),
        event_builder=EventBuilder(),
        event_scorer=EventScorer(),
        stage_reporter=stage_reporter,
    )


def create_marketplace_runner_factories(
    *,
    http_client: HttpClient,
    repository_scope_factory: RepositoryScopeFactory,
    processing_pipeline: MarketplacePipeline | None = None,
    stage_reporter: StageReporter | None = None,
) -> Mapping[str, MarketplaceIntegrationRunnerFactory]:
    """Create runner factories for currently supported marketplaces."""
    pipeline = processing_pipeline or create_marketplace_processing_pipeline(
        http_client,
        stage_reporter=stage_reporter,
    )

    def ggsel_factory(
        integration: MarketplaceIntegration,
    ) -> MarketplaceApplicationRunner:
        return MarketplaceApplicationRunner(
            marketplace=Marketplace.GGSEL,
            ingestion=pipeline.fetch_and_normalize,
            repository_scope_factory=repository_scope_factory,
            pipeline=pipeline,
            tenant_id=integration.tenant_id,
        )

    def playerok_factory(
        integration: MarketplaceIntegration,
    ) -> MarketplaceApplicationRunner:
        playerok_pipeline = PlayerokPipeline(
            fetcher=PlayerokFetcher(http_client),
            extractor=PlayerokExtractor(),
            normalizer=PlayerokNormalizer(),
        )
        return MarketplaceApplicationRunner(
            marketplace=Marketplace.PLAYEROK,
            ingestion=playerok_pipeline.run,
            repository_scope_factory=repository_scope_factory,
            pipeline=pipeline,
            tenant_id=integration.tenant_id,
        )

    def funpay_factory(
        integration: MarketplaceIntegration,
    ) -> MarketplaceApplicationRunner:
        funpay_pipeline = FunPayPipeline(
            fetcher=FunPayFetcher(http_client),
            extractor=FunPayExtractor(),
            normalizer=FunPayNormalizer(),
        )
        return MarketplaceApplicationRunner(
            marketplace=Marketplace.FUNPAY,
            ingestion=funpay_pipeline.run,
            repository_scope_factory=repository_scope_factory,
            pipeline=pipeline,
            tenant_id=integration.tenant_id,
        )

    return {
        Marketplace.GGSEL.value: ggsel_factory,
        Marketplace.PLAYEROK.value: playerok_factory,
        Marketplace.FUNPAY.value: funpay_factory,
    }
