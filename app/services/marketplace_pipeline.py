from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.analytics.models import PriceChange
from app.analytics.price_change import PriceChangeDetector
from app.comparator.difference import PriceDifferenceService
from app.comparator.grouping import OfferGroupingService
from app.comparator.models import MarketplaceOffer
from app.comparator.result import ComparisonResult, ComparisonResultBuilder
from app.comparator.selector import BestOfferSelector
from app.domain.events import PriceDropEvent
from app.domain.price_snapshot import PriceSnapshot
from app.insights.scoring import EventScorer
from app.models.canonical_product import CanonicalProduct
from app.parsers.ggsel_extractor import GGSelExtractor
from app.parsers.ggsel_fetcher import GGSelFetcher
from app.parsers.models import ParsedOffer
from app.parsers.normalizers import OfferNormalizer
from app.repositories.provider import RepositoryProvider
from app.services.content_generator import ContentGenerator
from app.services.event_builder import EventBuilder
from app.services.snapshot_builder import SnapshotBuilder

type StageReporter = Callable[[str], None]


@dataclass(slots=True, frozen=True)
class PreparedMarketplaceRun:
    """Repository-independent data prepared before transaction entry."""

    offers: tuple[ParsedOffer, ...]
    snapshots: tuple[PriceSnapshot, ...]
    skipped_offers: int
    errors: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class TransactionalMarketplaceResult:
    """Domain data and counts produced inside one repository scope."""

    offers_persisted: int
    comparison_results: tuple[ComparisonResult, ...]
    snapshots_persisted: int
    price_changes: tuple[PriceChange, ...]
    events: tuple[PriceDropEvent, ...]


@dataclass(slots=True, frozen=True)
class PostCommitMarketplaceResult:
    """Content processing outcome produced after persistence commits."""

    content_items_generated: int
    errors: tuple[str, ...]


class MarketplacePipeline:
    """Orchestrates pure marketplace processing phases."""

    def __init__(
        self,
        *,
        fetcher: GGSelFetcher,
        extractor: GGSelExtractor,
        normalizer: OfferNormalizer,
        snapshot_builder: SnapshotBuilder,
        price_change_detector: PriceChangeDetector,
        event_builder: EventBuilder,
        event_scorer: EventScorer,
        content_generator: ContentGenerator,
        repository_provider: RepositoryProvider | None = None,
        comparison_grouping: OfferGroupingService | None = None,
        comparison_selector: BestOfferSelector | None = None,
        comparison_difference: PriceDifferenceService | None = None,
        comparison_result_builder: ComparisonResultBuilder | None = None,
        stage_reporter: StageReporter | None = None,
    ) -> None:
        """Initialize the pipeline with existing project components."""
        self._fetcher = fetcher
        self._extractor = extractor
        self._normalizer = normalizer
        self._repository_provider = repository_provider
        self._snapshot_builder = snapshot_builder
        self._price_change_detector = price_change_detector
        self._event_builder = event_builder
        self._event_scorer = event_scorer
        self._content_generator = content_generator
        self._comparison_grouping = comparison_grouping or OfferGroupingService()
        self._comparison_selector = comparison_selector or BestOfferSelector()
        self._comparison_difference = (
            comparison_difference or PriceDifferenceService()
        )
        self._comparison_result_builder = (
            comparison_result_builder or ComparisonResultBuilder()
        )
        self._stage_reporter = stage_reporter

    async def fetch_and_normalize(self, url: str) -> list[ParsedOffer]:
        """Fetch, extract, and normalize GGSEL offers before persistence."""
        self._report("=== FETCH HTML ===")
        html = await self._fetcher.fetch_html(url)
        self._report(f"Fetched HTML: {len(html)} characters")

        self._report("=== EXTRACT RAW OFFERS ===")
        raw_offers = self._extractor.extract(html)
        self._report(f"Extracted raw offers: {len(raw_offers)}")
        if not raw_offers:
            self._report("No raw offers found.")
            return []

        self._report("=== NORMALIZE OFFERS ===")
        parsed_offers = [self._normalizer.normalize(offer) for offer in raw_offers]
        self._report(f"Normalized offers: {len(parsed_offers)}")
        return parsed_offers

    def prepare_offers(
        self,
        parsed_offers: Sequence[ParsedOffer],
    ) -> PreparedMarketplaceRun:
        """Build valid snapshot candidates before opening a transaction."""
        self._report("=== BUILD SNAPSHOTS ===")
        snapshots: list[PriceSnapshot] = []
        errors: list[str] = []

        for offer in parsed_offers:
            try:
                snapshots.append(self._snapshot_builder.build(offer))
            except ValueError as exc:
                identity = offer.external_id or "unknown"
                errors.append(
                    f"Skipped snapshot for {offer.marketplace}/{identity}: {exc}",
                )

        skipped_offers = len(parsed_offers) - len(snapshots)
        self._report(f"Built snapshots: {len(snapshots)}")
        self._report(f"Skipped snapshots: {skipped_offers}")
        return PreparedMarketplaceRun(
            offers=tuple(parsed_offers),
            snapshots=tuple(snapshots),
            skipped_offers=skipped_offers,
            errors=tuple(errors),
        )

    async def process_with_repositories(
        self,
        prepared: PreparedMarketplaceRun,
        repository_provider: RepositoryProvider,
    ) -> TransactionalMarketplaceResult:
        """Persist and process prepared offers within one repository scope."""
        for offer in prepared.offers:
            await repository_provider.offers.save(offer)
        self._report(f"Persisted offers: {len(prepared.offers)}")

        self._report("=== COMPARE OFFERS ===")
        comparison_results = await self.compare_repository_offers(
            repository_provider,
        )
        self._report(f"Comparison results: {len(comparison_results)}")

        self._report("=== UPDATE PRICE HISTORY ===")
        price_changes: list[PriceChange] = []
        for current_snapshot in prepared.snapshots:
            previous_snapshot = await repository_provider.price_history.get_last(
                current_snapshot.marketplace,
                current_snapshot.external_id,
            )
            await repository_provider.price_history.add(current_snapshot)

            if (
                previous_snapshot is None
                or current_snapshot.collected_at < previous_snapshot.collected_at
            ):
                continue

            price_change = self._price_change_detector.detect(
                previous_snapshot,
                current_snapshot,
            )
            if price_change is not None:
                price_changes.append(price_change)

        self._report(f"Stored snapshots: {len(prepared.snapshots)}")
        self._report("=== DETECT PRICE CHANGES ===")
        self._report(f"Detected price changes: {len(price_changes)}")

        self._report("=== BUILD EVENTS ===")
        events = tuple(
            event
            for price_change in price_changes
            if (event := self._event_builder.build(price_change)) is not None
        )
        self._report(f"Built events: {len(events)}")
        return TransactionalMarketplaceResult(
            offers_persisted=len(prepared.offers),
            comparison_results=tuple(comparison_results),
            snapshots_persisted=len(prepared.snapshots),
            price_changes=tuple(price_changes),
            events=events,
        )

    async def process_after_commit(
        self,
        events: Sequence[PriceDropEvent],
    ) -> PostCommitMarketplaceResult:
        """Score events and generate content after successful persistence."""
        errors: list[str] = []
        generated_count = 0

        self._report("=== SCORE EVENTS ===")
        if not events:
            self._report("No events to score.")

        for event in events:
            try:
                score = self._event_scorer.score(event)
            except Exception as exc:
                errors.append(self._post_commit_error("scoring", event, exc))
                continue
            self._report(f"Score: {score}")

            self._report("=== GENERATE CONTENT ===")
            try:
                post = await self._content_generator.generate(event)
            except Exception as exc:
                errors.append(self._post_commit_error("content", event, exc))
                continue
            generated_count += 1
            self._report(post)

        if generated_count == 0:
            self._report("No generated posts.")
        self._report(f"Generated posts: {generated_count}")
        return PostCommitMarketplaceResult(
            content_items_generated=generated_count,
            errors=tuple(errors),
        )

    async def run(self, url: str) -> list[ComparisonResult]:
        """Execute the compatibility flow with a preconfigured provider."""
        provider = self._require_repository_provider()
        parsed_offers = await self.fetch_and_normalize(url)
        prepared = self.prepare_offers(parsed_offers)
        transactional = await self.process_with_repositories(prepared, provider)
        await self.process_after_commit(transactional.events)
        return list(transactional.comparison_results)

    async def compare_offers(
        self,
        parsed_offers: Sequence[ParsedOffer],
        repository_provider: RepositoryProvider | None = None,
    ) -> list[ComparisonResult]:
        """Build comparison results for normalized marketplace offers."""
        provider = repository_provider or self._require_repository_provider()
        candidates = tuple(await provider.canonical_products.list_all())
        return self._build_comparison_results(parsed_offers, candidates)

    async def compare_repository_offers(
        self,
        repository_provider: RepositoryProvider | None = None,
    ) -> list[ComparisonResult]:
        """Build comparison results from offers stored in the repository."""
        provider = repository_provider or self._require_repository_provider()
        parsed_offers = await provider.offers.list_all()
        return await self.compare_offers(parsed_offers, provider)

    def _build_comparison_results(
        self,
        parsed_offers: Sequence[ParsedOffer],
        candidates: Sequence[CanonicalProduct],
    ) -> list[ComparisonResult]:
        grouped_offers = self._comparison_grouping.group(
            [MarketplaceOffer(offer=offer) for offer in parsed_offers],
            candidates,
        )
        canonical_index = {product.id: product for product in candidates}

        comparison_results: list[ComparisonResult] = []
        for group in grouped_offers:
            canonical_product = (
                canonical_index.get(group.canonical_product_id)
                if group.canonical_product_id is not None
                else None
            )
            selection = self._comparison_selector.select(group)
            difference = self._comparison_difference.compare(selection)
            comparison_results.append(
                self._comparison_result_builder.build(
                    canonical_product,
                    selection,
                    difference,
                ),
            )

        return comparison_results

    def _require_repository_provider(self) -> RepositoryProvider:
        if self._repository_provider is None:
            msg = "MarketplacePipeline requires a repository provider for this call."
            raise RuntimeError(msg)
        return self._repository_provider

    @staticmethod
    def _post_commit_error(
        phase: str,
        event: PriceDropEvent,
        exc: Exception,
    ) -> str:
        return (
            f"Post-commit {phase} failed for {event.marketplace}/{event.title}: "
            f"{type(exc).__name__}: {exc}"
        )

    def _report(self, message: str) -> None:
        if self._stage_reporter is not None:
            self._stage_reporter(message)
