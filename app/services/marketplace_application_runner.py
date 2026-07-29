from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from app.domain.marketplace import Marketplace
from app.parsers.models import ParsedOffer
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
    events_created: int
    content_items_generated: int
    persistence_committed: bool
    errors: tuple[str, ...]


class MarketplaceApplicationRunner:
    """Coordinate ingestion, transactional processing, and post-commit work."""

    def __init__(
        self,
        *,
        marketplace: Marketplace,
        ingestion: OfferIngestion,
        repository_scope_factory: RepositoryScopeFactory,
        pipeline: MarketplacePipeline,
    ) -> None:
        """Initialize one marketplace runner at the composition boundary."""
        self._marketplace = marketplace
        self._ingestion = ingestion
        self._repository_scope_factory = repository_scope_factory
        self._pipeline = pipeline

    async def run(self, url: str) -> MarketplaceRunResult:
        """Execute one bounded marketplace run with explicit phase ownership."""
        parsed_offers = tuple(await self._ingestion(url))
        prepared = self._pipeline.prepare_offers(parsed_offers)

        async with self._repository_scope_factory() as repository_provider:
            transactional = await self._pipeline.process_with_repositories(
                prepared,
                repository_provider,
            )

        post_commit = await self._pipeline.process_after_commit(transactional.events)
        return MarketplaceRunResult(
            marketplace=self._marketplace,
            offers_received=len(parsed_offers),
            offers_persisted=transactional.offers_persisted,
            comparison_results=len(transactional.comparison_results),
            snapshots_created=len(prepared.snapshots),
            snapshots_persisted=transactional.snapshots_persisted,
            skipped_offers=prepared.skipped_offers,
            price_changes_detected=len(transactional.price_changes),
            events_created=len(transactional.events),
            content_items_generated=post_commit.content_items_generated,
            persistence_committed=True,
            errors=prepared.errors + post_commit.errors,
        )
