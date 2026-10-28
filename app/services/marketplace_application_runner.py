from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID

from app.domain.marketplace import Marketplace
from app.domain.tenancy import LEGACY_TENANT_ID
from app.parsers.models import ParsedOffer
from app.repositories.offers import OfferObservationContext
from app.services.marketplace_pipeline import MarketplacePipeline
from app.services.repository_scope import RepositoryScopeFactory

type OfferIngestion = Callable[[str], Awaitable[Sequence[ParsedOffer]]]


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
        source_snapshot_complete: bool = False,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize one marketplace runner at the composition boundary."""
        self._marketplace = marketplace
        self._ingestion = ingestion
        self._repository_scope_factory = repository_scope_factory
        self._pipeline = pipeline
        self._tenant_id = tenant_id
        self._integration_id = integration_id
        self._source_snapshot_complete = source_snapshot_complete
        self._clock = clock or _utc_now

    async def run(self, url: str) -> MarketplaceRunResult:
        """Execute one bounded marketplace run with explicit phase ownership."""
        parsed_offers = tuple(
            replace(offer, tenant_id=self._tenant_id)
            for offer in await self._ingestion(url)
        )
        prepared = self._pipeline.prepare_offers(parsed_offers)
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

        async with self._repository_scope_factory() as repository_provider:
            transactional = await self._pipeline.process_with_repositories(
                prepared,
                repository_provider,
                observation_context=observation_context,
                reconcile_missing_offers=self._source_snapshot_complete,
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
        )


def _utc_now() -> datetime:
    return datetime.now(UTC)
