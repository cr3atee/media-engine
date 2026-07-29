from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Coroutine, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.analytics.models import PriceChange
from app.analytics.price_change import PriceChangeDetector
from app.database.repository_scope import create_postgres_repository_scope
from app.domain.events import PriceDropEvent
from app.domain.marketplace import Marketplace
from app.domain.price_snapshot import PriceSnapshot
from app.insights.scoring import EventScorer
from app.parsers.ggsel_extractor import GGSelExtractor
from app.parsers.ggsel_fetcher import GGSelFetcher
from app.parsers.models import ParsedOffer
from app.parsers.normalizers import OfferNormalizer
from app.repositories.memory import MemoryOfferRepository
from app.repositories.offers import OfferRepository
from app.repositories.postgres import (
    PostgresCanonicalProductRepository,
    PostgresOfferRepository,
    PostgresPriceHistoryRepository,
)
from app.repositories.price_history import PriceHistoryRepository
from app.repositories.provider import RepositoryProvider, create_memory_provider
from app.scheduler.jobs import GGSELJob, JobExecutionState
from app.services.content_generator import ContentGenerator
from app.services.event_builder import EventBuilder
from app.services.marketplace_application_runner import (
    MarketplaceApplicationRunner,
    MarketplaceRunResult,
)
from app.services.marketplace_pipeline import MarketplacePipeline
from app.services.repository_scope import create_memory_repository_scope
from app.services.snapshot_builder import SnapshotBuilder


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run async tests without requiring an external pytest plugin."""
    return asyncio.run(awaitable)


def make_offer(
    *,
    external_id: str = "1001",
    price: Decimal = Decimal("790"),
) -> ParsedOffer:
    """Create a valid normalized offer for runner tests."""
    return ParsedOffer(
        marketplace="ggsel",
        external_id=external_id,
        title="Minecraft Premium",
        url=f"https://ggsel.net/item/{external_id}",
        price=price,
        currency="RUB",
        seller_name="GGSEL Seller",
    )


@dataclass(slots=True)
class ScopeState:
    """Track repository-scope lifecycle events."""

    entered: int = 0
    committed: int = 0
    rolled_back: int = 0


class RecordingScopeFactory:
    """Record transaction-like lifecycle around one repository provider."""

    def __init__(
        self,
        provider: RepositoryProvider,
        timeline: list[str] | None = None,
    ) -> None:
        self.provider = provider
        self.state = ScopeState()
        self.timeline = timeline

    def __call__(self) -> AbstractAsyncContextManager[RepositoryProvider]:
        """Return a fresh recording context manager."""
        return self._scope()

    @asynccontextmanager
    async def _scope(self) -> AsyncIterator[RepositoryProvider]:
        self.state.entered += 1
        if self.timeline is not None:
            self.timeline.append("transaction_enter")
        try:
            yield self.provider
        except BaseException:
            self.state.rolled_back += 1
            if self.timeline is not None:
                self.timeline.append("transaction_rollback")
            raise
        else:
            self.state.committed += 1
            if self.timeline is not None:
                self.timeline.append("transaction_commit")


class RecordingIngestion:
    """Return prepared offers and record external I/O ordering."""

    def __init__(
        self,
        offers: Sequence[ParsedOffer],
        timeline: list[str] | None = None,
    ) -> None:
        self._offers = tuple(offers)
        self._timeline = timeline

    async def __call__(self, url: str) -> Sequence[ParsedOffer]:
        """Return normalized offers for one bounded source URL."""
        if self._timeline is not None:
            self._timeline.append("ingestion")
        return self._offers


class RecordingSnapshotBuilder(SnapshotBuilder):
    """Record pre-transaction validation and use the existing builder."""

    def __init__(self, timeline: list[str] | None = None) -> None:
        self._timeline = timeline

    def build(self, offer: ParsedOffer) -> PriceSnapshot:
        """Build a snapshot while recording phase ordering."""
        if self._timeline is not None:
            self._timeline.append("snapshot_preparation")
        return super().build(offer)


class FixedSnapshotBuilder(SnapshotBuilder):
    """Return one fixed snapshot for repeated-run idempotency tests."""

    def __init__(self, snapshot: PriceSnapshot) -> None:
        self._snapshot = snapshot

    def build(self, offer: ParsedOffer) -> PriceSnapshot:
        """Return the same exact snapshot for every run."""
        return self._snapshot


class RecordingContentGenerator(ContentGenerator):
    """Record post-commit content generation and optionally fail."""

    def __init__(
        self,
        *,
        timeline: list[str] | None = None,
        fail: bool = False,
    ) -> None:
        self.events: list[PriceDropEvent] = []
        self._timeline = timeline
        self._fail = fail

    async def generate(self, event: PriceDropEvent) -> str:
        """Record content work after persistence."""
        self.events.append(event)
        if self._timeline is not None:
            self._timeline.append("content")
        if self._fail:
            msg = "content provider failed"
            raise RuntimeError(msg)
        return "generated content"


class FailingOfferRepository(OfferRepository):
    """Fail on a configured write while preserving the repository contract."""

    def __init__(self, fail_on_call: int) -> None:
        self._delegate = MemoryOfferRepository()
        self._fail_on_call = fail_on_call
        self._save_calls = 0

    async def save(self, offer: ParsedOffer) -> None:
        """Fail on the selected save call."""
        self._save_calls += 1
        if self._save_calls == self._fail_on_call:
            msg = "offer write failed"
            raise RuntimeError(msg)
        await self._delegate.save(offer)

    async def get_by_identity(
        self,
        marketplace: str,
        external_id: str,
    ) -> ParsedOffer | None:
        """Delegate identity lookup."""
        return await self._delegate.get_by_identity(marketplace, external_id)

    async def list_by_marketplace(self, marketplace: str) -> Sequence[ParsedOffer]:
        """Delegate marketplace listing."""
        return await self._delegate.list_by_marketplace(marketplace)

    async def list_all(self) -> Sequence[ParsedOffer]:
        """Delegate complete listing."""
        return await self._delegate.list_all()


class FailingPriceHistoryRepository(PriceHistoryRepository):
    """Price-history contract double that fails every write."""

    async def add(self, snapshot: PriceSnapshot) -> bool:
        """Raise a deterministic persistence failure."""
        msg = "snapshot write failed"
        raise RuntimeError(msg)

    async def get_last(
        self,
        marketplace: str,
        external_id: str,
    ) -> PriceSnapshot | None:
        """Return no previous snapshot."""
        return None

    async def get_previous(
        self,
        marketplace: str,
        external_id: str,
    ) -> PriceSnapshot | None:
        """Return no previous snapshot."""
        return None

    async def get_history(
        self,
        marketplace: str,
        external_id: str,
    ) -> list[PriceSnapshot]:
        """Return empty history."""
        return []


class FailingPriceChangeDetector(PriceChangeDetector):
    """Raise during deterministic transaction-phase processing."""

    def detect(
        self,
        previous: PriceSnapshot,
        current: PriceSnapshot,
    ) -> PriceChange | None:
        """Raise a deterministic calculation failure."""
        msg = "price change calculation failed"
        raise RuntimeError(msg)


class RecordingApplicationRunner:
    """Runner double used to verify scheduler delegation."""

    def __init__(self) -> None:
        self.urls: list[str] = []

    async def run(self, url: str) -> MarketplaceRunResult:
        """Record the URL and return an empty successful result."""
        self.urls.append(url)
        return MarketplaceRunResult(
            marketplace=Marketplace.GGSEL,
            offers_received=0,
            offers_persisted=0,
            comparison_results=0,
            snapshots_created=0,
            snapshots_persisted=0,
            skipped_offers=0,
            price_changes_detected=0,
            events_created=0,
            content_items_generated=0,
            persistence_committed=True,
            errors=(),
        )


def make_pipeline(
    *,
    snapshot_builder: SnapshotBuilder | None = None,
    price_change_detector: PriceChangeDetector | None = None,
    content_generator: ContentGenerator | None = None,
) -> MarketplacePipeline:
    """Build transaction processing with unused GGSEL ingestion collaborators."""
    return MarketplacePipeline(
        fetcher=cast(GGSelFetcher, object()),
        extractor=cast(GGSelExtractor, object()),
        normalizer=OfferNormalizer(),
        snapshot_builder=snapshot_builder or SnapshotBuilder(),
        price_change_detector=price_change_detector or PriceChangeDetector(),
        event_builder=EventBuilder(),
        event_scorer=EventScorer(),
        content_generator=content_generator or RecordingContentGenerator(),
    )


def make_runner(
    *,
    offers: Sequence[ParsedOffer],
    pipeline: MarketplacePipeline,
    scope_factory: RecordingScopeFactory,
    timeline: list[str] | None = None,
) -> MarketplaceApplicationRunner:
    """Build the application runner with deterministic collaborators."""
    return MarketplaceApplicationRunner(
        marketplace=Marketplace.GGSEL,
        ingestion=RecordingIngestion(offers, timeline),
        repository_scope_factory=scope_factory,
        pipeline=pipeline,
    )


def test_successful_run_orders_phases_and_reports_counts() -> None:
    timeline: list[str] = []
    provider = create_memory_provider()
    previous = PriceSnapshot(
        marketplace="ggsel",
        external_id="1001",
        price=Decimal("990"),
        currency="RUB",
        collected_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    run_async(provider.price_history.add(previous))
    content = RecordingContentGenerator(timeline=timeline)
    pipeline = make_pipeline(
        snapshot_builder=RecordingSnapshotBuilder(timeline),
        content_generator=content,
    )
    scope = RecordingScopeFactory(provider, timeline)
    runner = make_runner(
        offers=(make_offer(),),
        pipeline=pipeline,
        scope_factory=scope,
        timeline=timeline,
    )

    result = run_async(runner.run("demo://ggsel"))

    assert timeline == [
        "ingestion",
        "snapshot_preparation",
        "transaction_enter",
        "transaction_commit",
        "content",
    ]
    assert scope.state == ScopeState(entered=1, committed=1, rolled_back=0)
    assert result.offers_received == 1
    assert result.offers_persisted == 1
    assert result.snapshots_created == 1
    assert result.snapshots_persisted == 1
    assert result.price_changes_detected == 1
    assert result.events_created == 1
    assert result.content_items_generated == 1
    assert result.persistence_committed is True
    assert result.errors == ()


def test_offer_repository_failure_rolls_back_and_skips_post_commit() -> None:
    provider = create_memory_provider()
    provider.offers = FailingOfferRepository(fail_on_call=2)
    content = RecordingContentGenerator()
    pipeline = make_pipeline(content_generator=content)
    scope = RecordingScopeFactory(provider)
    runner = make_runner(
        offers=(make_offer(), make_offer(external_id="1002")),
        pipeline=pipeline,
        scope_factory=scope,
    )

    with pytest.raises(RuntimeError, match="offer write failed"):
        run_async(runner.run("demo://ggsel"))

    assert scope.state == ScopeState(entered=1, committed=0, rolled_back=1)
    assert content.events == []


def test_snapshot_failure_rolls_back_offer_and_snapshot_work() -> None:
    provider = create_memory_provider()
    provider.price_history = FailingPriceHistoryRepository()
    content = RecordingContentGenerator()
    scope = RecordingScopeFactory(provider)
    runner = make_runner(
        offers=(make_offer(),),
        pipeline=make_pipeline(content_generator=content),
        scope_factory=scope,
    )

    with pytest.raises(RuntimeError, match="snapshot write failed"):
        run_async(runner.run("demo://ggsel"))

    assert scope.state == ScopeState(entered=1, committed=0, rolled_back=1)
    assert content.events == []


def test_deterministic_processing_failure_rolls_back() -> None:
    provider = create_memory_provider()
    run_async(
        provider.price_history.add(
            PriceSnapshot(
                marketplace="ggsel",
                external_id="1001",
                price=Decimal("990"),
                currency="RUB",
                collected_at=datetime.now(UTC) - timedelta(minutes=1),
            ),
        ),
    )
    content = RecordingContentGenerator()
    scope = RecordingScopeFactory(provider)
    runner = make_runner(
        offers=(make_offer(),),
        pipeline=make_pipeline(
            price_change_detector=FailingPriceChangeDetector(),
            content_generator=content,
        ),
        scope_factory=scope,
    )

    with pytest.raises(RuntimeError, match="price change calculation failed"):
        run_async(runner.run("demo://ggsel"))

    assert scope.state == ScopeState(entered=1, committed=0, rolled_back=1)
    assert content.events == []


def test_content_failure_is_reported_after_commit() -> None:
    provider = create_memory_provider()
    run_async(
        provider.price_history.add(
            PriceSnapshot(
                marketplace="ggsel",
                external_id="1001",
                price=Decimal("990"),
                currency="RUB",
                collected_at=datetime.now(UTC) - timedelta(minutes=1),
            ),
        ),
    )
    content = RecordingContentGenerator(fail=True)
    scope = RecordingScopeFactory(provider)
    runner = make_runner(
        offers=(make_offer(),),
        pipeline=make_pipeline(content_generator=content),
        scope_factory=scope,
    )

    result = run_async(runner.run("demo://ggsel"))

    assert scope.state == ScopeState(entered=1, committed=1, rolled_back=0)
    assert result.persistence_committed is True
    assert result.content_items_generated == 0
    assert len(result.errors) == 1
    assert "Post-commit content failed" in result.errors[0]
    assert len(run_async(provider.offers.list_all())) == 1
    assert len(run_async(provider.price_history.get_history("ggsel", "1001"))) == 2


def test_memory_scope_reuses_state_without_sqlalchemy_transaction_objects() -> None:
    provider = create_memory_provider()
    scope_factory = create_memory_repository_scope(provider)
    pipeline = make_pipeline()
    runner = MarketplaceApplicationRunner(
        marketplace=Marketplace.GGSEL,
        ingestion=RecordingIngestion((make_offer(),)),
        repository_scope_factory=scope_factory,
        pipeline=pipeline,
    )

    first = run_async(runner.run("demo://ggsel"))
    second = run_async(runner.run("demo://ggsel"))

    assert first.persistence_committed is True
    assert second.persistence_committed is True
    assert len(run_async(provider.offers.list_all())) == 1
    assert len(run_async(provider.price_history.get_history("ggsel", "1001"))) == 2


def test_repeated_exact_snapshot_reports_one_persisted_record() -> None:
    provider = create_memory_provider()
    scope_factory = create_memory_repository_scope(provider)
    snapshot = PriceSnapshot(
        marketplace="ggsel",
        external_id="1001",
        price=Decimal("790"),
        currency="RUB",
        collected_at=datetime.now(UTC),
    )
    pipeline = make_pipeline(snapshot_builder=FixedSnapshotBuilder(snapshot))
    runner = MarketplaceApplicationRunner(
        marketplace=Marketplace.GGSEL,
        ingestion=RecordingIngestion((make_offer(),)),
        repository_scope_factory=scope_factory,
        pipeline=pipeline,
    )

    first = run_async(runner.run("demo://ggsel"))
    second = run_async(runner.run("demo://ggsel"))

    assert first.snapshots_persisted == 1
    assert second.snapshots_persisted == 0
    assert len(run_async(provider.offers.list_all())) == 1
    assert run_async(provider.price_history.get_history("ggsel", "1001")) == [
        snapshot,
    ]


def test_postgres_scope_binds_all_repositories_to_one_session() -> None:
    session_factory = async_sessionmaker(expire_on_commit=False)
    scope_factory = create_postgres_repository_scope(session_factory)

    async def inspect_scope() -> set[int]:
        async with scope_factory() as provider:
            return {
                id(
                    cast(
                        PostgresCanonicalProductRepository,
                        provider.canonical_products,
                    )._session,
                ),
                id(cast(PostgresOfferRepository, provider.offers)._session),
                id(
                    cast(
                        PostgresPriceHistoryRepository,
                        provider.price_history,
                    )._session,
                ),
            }

    assert len(run_async(inspect_scope())) == 1


def test_scheduler_job_delegates_to_application_runner() -> None:
    runner = RecordingApplicationRunner()
    job = GGSELJob(runner, url="demo://ggsel")

    run_async(job.execute())

    assert runner.urls == ["demo://ggsel"]
    assert job.status.state is JobExecutionState.SUCCEEDED
