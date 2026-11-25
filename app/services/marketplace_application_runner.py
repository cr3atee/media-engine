from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID

from app.domain.marketplace import Marketplace
from app.domain.marketplace_integrations import MarketplaceIntegrationStatus
from app.domain.tenancy import LEGACY_TENANT_ID
from app.parsers.models import ParsedOffer
from app.parsers.source_snapshot import SourceSnapshotEvidence
from app.repositories.offers import OfferObservationContext
from app.repositories.provider import RepositoryProvider
from app.services.catalog_classification import CatalogClassificationService
from app.services.marketplace_ingestion import MarketplaceIngestionResult
from app.services.marketplace_pipeline import MarketplacePipeline
from app.services.repository_scope import RepositoryScopeFactory

type OfferIngestion = Callable[
    [str],
    Awaitable[Sequence[ParsedOffer] | MarketplaceIngestionResult],
]


class PriceRefreshScopeError(ValueError):
    """A source quote no longer matches the explicitly reviewed refresh scope."""


@dataclass(slots=True, frozen=True)
class MarketplaceRunResult:
    """Backend-neutral summary of one marketplace application run."""

    marketplace: Marketplace
    offers_received: int
    offers_persisted: int
    comparison_results: int
    snapshots_created: int
    snapshots_persisted: int
    skipped_offers: int
    price_changes_detected: int
    event_candidates_built: int
    events_created: int
    events_existing: int
    skipped_event_candidates: int
    event_ids: tuple[UUID, ...]
    events_scored: int
    content_items_generated: int
    persistence_committed: bool
    errors: tuple[str, ...]
    offers_deactivated: int = 0
    tenant_id: UUID = LEGACY_TENANT_ID
    source_items: int = 0
    source_items_expected: int | None = None
    source_snapshot_complete: bool = False
    source_snapshot_reason: str = "Source completeness evidence was not provided."


class MarketplaceApplicationRunner:
    """Coordinate ingestion, transactional processing, and post-commit work."""

    def __init__(
        self,
        *,
        marketplace: Marketplace,
        ingestion: OfferIngestion,
        repository_scope_factory: RepositoryScopeFactory,
        pipeline: MarketplacePipeline,
        tenant_id: UUID = LEGACY_TENANT_ID,
        integration_id: UUID | None = None,
        catalog_classification: CatalogClassificationService | None = None,
        source_snapshot_complete: bool = False,
        clock: Callable[[], datetime] | None = None,
        price_refresh_targets: Mapping[str, UUID] | None = None,
    ) -> None:
        """Initialize one marketplace runner at the composition boundary."""
        self._marketplace = marketplace
        self._ingestion = ingestion
        self._repository_scope_factory = repository_scope_factory
        self._pipeline = pipeline
        self._tenant_id = tenant_id
        self._integration_id = integration_id
        self._catalog_classification = catalog_classification
        self._source_snapshot_complete = source_snapshot_complete
        self._clock = clock or _utc_now
        if price_refresh_targets is not None and (
            not price_refresh_targets or integration_id is None
        ):
            raise ValueError("Price refresh requires explicit targets and integration.")
        self._price_refresh_targets = (
            dict(price_refresh_targets) if price_refresh_targets is not None else None
        )

    async def run(self, url: str) -> MarketplaceRunResult:
        """Execute one bounded marketplace run with explicit phase ownership."""
        ingestion = await self._ingestion(url)
        if isinstance(ingestion, MarketplaceIngestionResult):
            source_offers = ingestion.offers
            source_evidence = ingestion.evidence
        else:
            source_offers = tuple(ingestion)
            source_evidence = SourceSnapshotEvidence(
                source_items=len(source_offers),
                parsed_items=len(source_offers),
                complete=self._source_snapshot_complete,
                reason=(
                    "Legacy ingestion was explicitly marked complete."
                    if self._source_snapshot_complete
                    else "Legacy ingestion did not provide completeness evidence."
                ),
            )
        parsed_offers = tuple(
            replace(offer, tenant_id=self._tenant_id) for offer in source_offers
        )
        observation_context = (
            OfferObservationContext(
                tenant_id=self._tenant_id,
                integration_id=self._integration_id,
                marketplace=self._marketplace.value,
                observed_at=self._clock(),
            )
            if self._integration_id is not None
            else None
        )

        if self._price_refresh_targets is not None:
            async with self._repository_scope_factory() as repository_provider:
                selected = await self._select_price_refresh_offers(
                    repository_provider, parsed_offers, url
                )
                prepared = self._pipeline.prepare_offers(selected)
                transactional = await self._pipeline.process_with_repositories(
                    prepared,
                    repository_provider,
                    observation_context=observation_context,
                    reconcile_missing_offers=False,
                )
        elif (
            self._catalog_classification is not None
            and self._integration_id is not None
        ):
            async with self._repository_scope_factory() as repository_provider:
                classifications = (
                    await self._catalog_classification.classify_with_repositories(
                        repository_provider,
                        self._tenant_id,
                        self._integration_id,
                        parsed_offers,
                    )
                )
                prepared = self._pipeline.prepare_offers(
                    tuple(result.apply() for result in classifications)
                )
                transactional = await self._pipeline.process_with_repositories(
                    prepared,
                    repository_provider,
                    observation_context=observation_context,
                    reconcile_missing_offers=source_evidence.complete,
                )
        else:
            prepared = self._pipeline.prepare_offers(parsed_offers)
            async with self._repository_scope_factory() as repository_provider:
                transactional = await self._pipeline.process_with_repositories(
                    prepared,
                    repository_provider,
                    observation_context=observation_context,
                    reconcile_missing_offers=source_evidence.complete,
                )

        return MarketplaceRunResult(
            marketplace=self._marketplace,
            offers_received=len(parsed_offers),
            offers_persisted=transactional.offers_persisted,
            comparison_results=len(transactional.comparison_results),
            snapshots_created=len(prepared.snapshots),
            snapshots_persisted=transactional.snapshots_persisted,
            skipped_offers=prepared.skipped_offers,
            price_changes_detected=len(transactional.price_changes),
            event_candidates_built=len(transactional.event_results),
            events_created=transactional.events_created,
            events_existing=transactional.events_existing,
            skipped_event_candidates=transactional.skipped_event_candidates,
            event_ids=tuple(event.id for event in transactional.durable_events),
            events_scored=0,
            content_items_generated=0,
            persistence_committed=True,
            errors=prepared.errors,
            offers_deactivated=transactional.offers_deactivated,
            tenant_id=self._tenant_id,
            source_items=source_evidence.source_items,
            source_items_expected=source_evidence.expected_items,
            source_snapshot_complete=source_evidence.complete,
            source_snapshot_reason=source_evidence.reason,
        )

    async def _select_price_refresh_offers(
        self,
        repositories: RepositoryProvider,
        offers: Sequence[ParsedOffer],
        source_url: str,
    ) -> tuple[ParsedOffer, ...]:
        """Merge only fresh prices into currently active, still-reviewed rows."""
        assert self._price_refresh_targets is not None
        assert self._integration_id is not None
        integration = await repositories.marketplace_integrations.get_by_tenant_and_id(
            self._tenant_id, self._integration_id
        )
        tenant = await repositories.tenants.get_by_id(self._tenant_id)
        if (
            tenant is None
            or not tenant.is_active
            or integration is None
            or not integration.enabled
            or integration.status is not MarketplaceIntegrationStatus.ACTIVE
            or integration.marketplace != self._marketplace.value
            or integration.source_url != source_url
        ):
            raise PriceRefreshScopeError(
                "Price refresh integration is no longer active."
            )
        incoming: dict[str, ParsedOffer] = {}
        for offer in offers:
            identity = offer.external_id
            if identity not in self._price_refresh_targets:
                continue
            assert identity is not None
            if identity in incoming or offer.marketplace != self._marketplace.value:
                raise PriceRefreshScopeError("Ambiguous price refresh source identity.")
            incoming[identity] = offer
        if incoming.keys() != self._price_refresh_targets.keys():
            raise PriceRefreshScopeError(
                "A reviewed offer is absent from the response."
            )
        selected: list[ParsedOffer] = []
        for identity, product_id in sorted(self._price_refresh_targets.items()):
            fresh = incoming[identity]
            stored = await repositories.offers.get_by_identity_for_update(
                self._tenant_id, self._marketplace.value, identity
            )
            if stored is None or stored.canonical_product_id != product_id:
                raise PriceRefreshScopeError("Reviewed offer ownership has changed.")
            if stored.source_category_id is None:
                raise PriceRefreshScopeError("Reviewed offer lacks a source category.")
            rule = await repositories.catalog_source_rules.get_by_source(
                self._tenant_id,
                self._integration_id,
                self._marketplace.value,
                stored.source_category_id,
            )
            if (
                rule is None
                or rule.id != stored.catalog_source_rule_id
                or rule.hub_code != stored.catalog_hub_code
                or rule.section_code != stored.catalog_section_code
            ):
                raise PriceRefreshScopeError("Reviewed source mapping has changed.")
            if (
                fresh.price is None
                or not fresh.price.is_finite()
                or fresh.price <= 0
                or fresh.currency != stored.currency
                or any(
                    getattr(fresh, name) != getattr(stored, name)
                    for name in (
                        "title",
                        "url",
                        "seller_id",
                        "seller_name",
                        "source_category_id",
                    )
                )
            ):
                raise PriceRefreshScopeError(
                    "Reviewed source context or price changed."
                )
            selected.append(replace(stored, price=fresh.price))
        return tuple(selected)


def _utc_now() -> datetime:
    return datetime.now(UTC)
