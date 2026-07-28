from __future__ import annotations

from collections.abc import Callable, Sequence

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
from app.services.price_history import PriceHistoryService
from app.services.snapshot_builder import SnapshotBuilder

type StageReporter = Callable[[str], None]


class MarketplacePipeline:
    """Orchestrates marketplace offer processing without persistence or delivery."""

    def __init__(
        self,
        *,
        fetcher: GGSelFetcher,
        extractor: GGSelExtractor,
        normalizer: OfferNormalizer,
        repository_provider: RepositoryProvider,
        snapshot_builder: SnapshotBuilder,
        price_history: PriceHistoryService,
        price_change_detector: PriceChangeDetector,
        event_builder: EventBuilder,
        event_scorer: EventScorer,
        content_generator: ContentGenerator,
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
        self._price_history = price_history
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

    async def run(self, url: str) -> list[ComparisonResult]:
        """Execute the full marketplace processing pipeline for one source URL."""
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
        for offer in parsed_offers:
            await self._repository_provider.offers.save(offer)
        self._report(f"Persisted offers: {len(parsed_offers)}")

        self._report("=== COMPARE OFFERS ===")
        comparison_results = await self.compare_repository_offers()
        self._report(f"Comparison results: {len(comparison_results)}")

        self._report("=== BUILD SNAPSHOTS ===")
        snapshots: list[PriceSnapshot] = []
        skipped_snapshots_count = 0
        for offer in parsed_offers:
            try:
                snapshots.append(self._snapshot_builder.build(offer))
            except ValueError:
                skipped_snapshots_count += 1

        self._report(f"Built snapshots: {len(snapshots)}")
        self._report(f"Skipped snapshots: {skipped_snapshots_count}")

        self._report("=== UPDATE PRICE HISTORY ===")
        snapshots_count = 0
        price_changes: list[PriceChange] = []

        for current_snapshot in snapshots:
            previous_snapshot = self._price_history.get_last(
                current_snapshot.marketplace,
                current_snapshot.external_id,
            )
            self._price_history.add(current_snapshot)
            snapshots_count += 1

            if previous_snapshot is None:
                continue

            price_change = self._price_change_detector.detect(
                previous_snapshot,
                current_snapshot,
            )
            if price_change is not None:
                price_changes.append(price_change)

        self._report(f"Stored snapshots: {snapshots_count}")

        self._report("=== DETECT PRICE CHANGES ===")
        self._report(f"Detected price changes: {len(price_changes)}")

        self._report("=== BUILD EVENTS ===")
        events: list[PriceDropEvent] = []
        for price_change in price_changes:
            event = self._event_builder.build(price_change)
            if event is not None:
                events.append(event)
        self._report(f"Built events: {len(events)}")

        self._report("=== SCORE EVENTS ===")
        if not events:
            self._report("No events to score.")
        for event in events:
            self._report(f"Score: {self._event_scorer.score(event)}")

        self._report("=== GENERATE CONTENT ===")
        posts_count = 0
        for event in events:
            post = await self._content_generator.generate(event)
            posts_count += 1
            self._report(post)
        if posts_count == 0:
            self._report("No generated posts.")
        self._report(f"Generated posts: {posts_count}")
        return comparison_results

    async def compare_offers(
        self,
        parsed_offers: Sequence[ParsedOffer],
    ) -> list[ComparisonResult]:
        """Build comparison results for normalized marketplace offers."""
        candidates = tuple(
            await self._repository_provider.canonical_products.list_all(),
        )
        return self._build_comparison_results(parsed_offers, candidates)

    async def compare_repository_offers(self) -> list[ComparisonResult]:
        """Build comparison results from offers stored in the repository."""
        parsed_offers = await self._repository_provider.offers.list_all()
        return await self.compare_offers(parsed_offers)

    def _build_comparison_results(
        self,
        parsed_offers: Sequence[ParsedOffer],
        candidates: Sequence[CanonicalProduct],
    ) -> list[ComparisonResult]:
        """Build comparison results after repository data has already loaded."""
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

    def _report(self, message: str) -> None:
        if self._stage_reporter is not None:
            self._stage_reporter(message)
