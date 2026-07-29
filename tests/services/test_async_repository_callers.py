from __future__ import annotations

import asyncio
import inspect
from collections.abc import Coroutine, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from app.ai.fake_provider import FakeAIProvider
from app.analytics.models import PriceChange
from app.analytics.price_change import PriceChangeDetector
from app.comparator.result import ComparisonStatus
from app.domain.events import PriceDropEvent
from app.domain.price_snapshot import PriceSnapshot
from app.insights.scoring import EventScorer
from app.models.canonical_product import CanonicalProduct
from app.parsers.ggsel_extractor import GGSelExtractor
from app.parsers.ggsel_fetcher import GGSelFetcher
from app.parsers.models import ParsedOffer, RawMarketplaceOffer
from app.parsers.normalizers import OfferNormalizer
from app.parsers.playerok_extractor import PlayerokExtractor
from app.parsers.playerok_fetcher import PlayerokFetcher
from app.parsers.playerok_normalizer import PlayerokNormalizer
from app.repositories.canonical_products import CanonicalProductRepository
from app.repositories.memory import (
    MemoryGeneratedContentRepository,
    MemoryMarketEventRepository,
    MemoryPublicationRepository,
)
from app.repositories.offers import OfferRepository
from app.repositories.price_history import PriceHistoryRepository
from app.repositories.provider import RepositoryProvider
from app.services.content_generator import ContentGenerator
from app.services.event_builder import EventBuilder
from app.services.marketplace_pipeline import MarketplacePipeline
from app.services.playerok_pipeline import PlayerokPipeline
from app.services.snapshot_builder import SnapshotBuilder


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run async application callers without requiring an external pytest plugin."""
    return asyncio.run(awaitable)


@dataclass(slots=True)
class AsyncCallState:
    """Tracks whether repository methods were awaited by application callers."""

    offer_save_count: int = 0
    offer_list_count: int = 0
    canonical_list_count: int = 0
    history_add_count: int = 0
    history_get_last_count: int = 0


class RecordingOfferRepository(OfferRepository):
    """Offer repository double that exposes async call counters."""

    def __init__(
        self,
        state: AsyncCallState,
        *,
        fail_on_save: bool = False,
    ) -> None:
        self._state = state
        self._offers: list[ParsedOffer] = []
        self._fail_on_save = fail_on_save

    async def save(self, offer: ParsedOffer) -> None:
        """Store an offer and record an awaited save operation."""
        self._state.offer_save_count += 1
        if self._fail_on_save:
            msg = "offer repository failed"
            raise RuntimeError(msg)
        self._offers.append(offer)

    async def get_by_identity(
        self,
        marketplace: str,
        external_id: str,
    ) -> ParsedOffer | None:
        """Return an offer by marketplace and external identifier."""
        for offer in self._offers:
            if offer.marketplace == marketplace and offer.external_id == external_id:
                return offer
        return None

    async def list_by_marketplace(self, marketplace: str) -> Sequence[ParsedOffer]:
        """Return offers from one marketplace."""
        return tuple(
            offer for offer in self._offers if offer.marketplace == marketplace
        )

    async def list_all(self) -> Sequence[ParsedOffer]:
        """Return all offers and record an awaited list operation."""
        self._state.offer_list_count += 1
        return tuple(self._offers)


class RecordingCanonicalProductRepository(CanonicalProductRepository):
    """Canonical product repository double that exposes async list usage."""

    def __init__(
        self,
        state: AsyncCallState,
        products: Sequence[CanonicalProduct],
    ) -> None:
        self._state = state
        self._products = {product.id: product for product in products}

    async def save(self, product: CanonicalProduct) -> None:
        """Store a canonical product."""
        self._products[product.id] = product

    async def get_by_id(self, id: UUID) -> CanonicalProduct | None:
        """Return a canonical product by identifier."""
        return self._products.get(id)

    async def list_all(self) -> Sequence[CanonicalProduct]:
        """Return all products and record an awaited list operation."""
        self._state.canonical_list_count += 1
        return tuple(self._products.values())


class RecordingPriceHistoryRepository(PriceHistoryRepository):
    """Price-history repository double that records awaited operations."""

    def __init__(
        self,
        state: AsyncCallState,
        *,
        fail_on_read: bool = False,
        fail_on_write: bool = False,
    ) -> None:
        self._state = state
        self._history: list[PriceSnapshot] = []
        self._fail_on_read = fail_on_read
        self._fail_on_write = fail_on_write

    async def add(self, snapshot: PriceSnapshot) -> bool:
        """Store a snapshot and record the awaited write."""
        self._state.history_add_count += 1
        if self._fail_on_write:
            msg = "price history write failed"
            raise RuntimeError(msg)
        if snapshot in self._history:
            return False
        self._history.append(snapshot)
        return True

    async def get_last(
        self,
        marketplace: str,
        external_id: str,
    ) -> PriceSnapshot | None:
        """Return the latest matching snapshot and record the awaited read."""
        self._state.history_get_last_count += 1
        if self._fail_on_read:
            msg = "price history read failed"
            raise RuntimeError(msg)
        history = await self.get_history(marketplace, external_id)
        return history[-1] if history else None

    async def get_previous(
        self,
        marketplace: str,
        external_id: str,
    ) -> PriceSnapshot | None:
        """Return the snapshot before the latest matching snapshot."""
        history = await self.get_history(marketplace, external_id)
        return history[-2] if len(history) >= 2 else None

    async def get_history(
        self,
        marketplace: str,
        external_id: str,
    ) -> list[PriceSnapshot]:
        """Return matching snapshots in deterministic chronological order."""
        return sorted(
            (
                snapshot
                for snapshot in self._history
                if snapshot.marketplace == marketplace
                and snapshot.external_id == external_id
            ),
            key=lambda snapshot: snapshot.collected_at,
        )


class StaticGGSelFetcher:
    """Returns deterministic HTML for marketplace pipeline tests."""

    async def fetch_html(self, url: str) -> str:
        """Return raw source content."""
        return "<html>ok</html>"


class StaticGGSelExtractor:
    """Returns deterministic raw GGSEL offers for marketplace pipeline tests."""

    def extract(self, html: str) -> list[RawMarketplaceOffer]:
        """Return one raw marketplace offer."""
        return [
            RawMarketplaceOffer(
                id_goods=1001,
                name="Minecraft Premium",
                url="https://ggsel.net/item/1001",
                seller_name="GGSEL Seller",
                id_section=1,
                price=790.0,
                currency="RUB",
            ),
        ]


class SequencedSnapshotBuilder(SnapshotBuilder):
    """Returns deterministic snapshots in the order supplied by a test."""

    def __init__(self, snapshots: Sequence[PriceSnapshot]) -> None:
        self._snapshots = list(snapshots)

    def build(self, offer: ParsedOffer) -> PriceSnapshot:
        """Return the next prepared snapshot."""
        return self._snapshots.pop(0)


class FailingSnapshotBuilder(SnapshotBuilder):
    """Raises the validation error expected from an incomplete offer."""

    def build(self, offer: ParsedOffer) -> PriceSnapshot:
        """Reject snapshot construction."""
        msg = "ParsedOffer does not contain required PriceSnapshot fields."
        raise ValueError(msg)


class RecordingContentGenerator(ContentGenerator):
    """Records price-drop events passed to the existing content boundary."""

    def __init__(self) -> None:
        self.events: list[PriceDropEvent] = []

    async def generate(self, event: PriceDropEvent) -> str:
        """Record an event and return deterministic generated content."""
        self.events.append(event)
        return "generated content"


class RecordingPriceChangeDetector(PriceChangeDetector):
    """Records concrete snapshots received after async repository access."""

    def __init__(self) -> None:
        self.calls: list[tuple[PriceSnapshot, PriceSnapshot]] = []

    def detect(
        self,
        previous: PriceSnapshot,
        current: PriceSnapshot,
    ) -> PriceChange | None:
        """Record detector inputs before delegating to the active detector."""
        self.calls.append((previous, current))
        return super().detect(previous, current)


def make_product() -> CanonicalProduct:
    """Create a canonical product used by repository-backed comparison."""
    return CanonicalProduct(
        id=uuid4(),
        name="Minecraft Premium",
        category="games",
        aliases=("minecraft",),
    )


def make_offer(
    *,
    marketplace: str = "ggsel",
    external_id: str = "1001",
    price: Decimal = Decimal("790"),
) -> ParsedOffer:
    """Create a parsed offer used by application caller tests."""
    return ParsedOffer(
        marketplace=marketplace,
        external_id=external_id,
        title="Minecraft Premium",
        url=f"https://example.com/{marketplace}/{external_id}",
        price=price,
        currency="RUB",
        seller_id=None,
        seller_name=f"{marketplace} seller",
    )


def make_snapshot(
    *,
    marketplace: str = "ggsel",
    external_id: str = "1001",
    price: Decimal = Decimal("790"),
    collected_at: datetime | None = None,
) -> PriceSnapshot:
    """Create a deterministic marketplace price snapshot."""
    return PriceSnapshot(
        marketplace=marketplace,
        external_id=external_id,
        price=price,
        currency="RUB",
        collected_at=collected_at or datetime.now(UTC),
    )


def make_pipeline(
    provider: RepositoryProvider,
    *,
    snapshot_builder: SnapshotBuilder | None = None,
    content_generator: ContentGenerator | None = None,
    price_change_detector: PriceChangeDetector | None = None,
    stage_reporter: list[str] | None = None,
) -> MarketplacePipeline:
    """Build the existing marketplace pipeline with deterministic test doubles."""
    return MarketplacePipeline(
        fetcher=cast(GGSelFetcher, StaticGGSelFetcher()),
        extractor=cast(GGSelExtractor, StaticGGSelExtractor()),
        normalizer=OfferNormalizer(marketplace="ggsel"),
        repository_provider=provider,
        snapshot_builder=snapshot_builder or SnapshotBuilder(),
        price_change_detector=price_change_detector or PriceChangeDetector(),
        event_builder=EventBuilder(),
        event_scorer=EventScorer(),
        content_generator=content_generator or ContentGenerator(FakeAIProvider()),
        stage_reporter=stage_reporter.append if stage_reporter is not None else None,
    )


def make_provider(
    *,
    product: CanonicalProduct,
    fail_on_offer_save: bool = False,
    fail_on_history_read: bool = False,
    fail_on_history_write: bool = False,
) -> tuple[RepositoryProvider, AsyncCallState]:
    """Build a repository provider with async-aware repository doubles."""
    state = AsyncCallState()
    return (
        RepositoryProvider(
            canonical_products=RecordingCanonicalProductRepository(
                state,
                (product,),
            ),
            offers=RecordingOfferRepository(
                state,
                fail_on_save=fail_on_offer_save,
            ),
            price_history=RecordingPriceHistoryRepository(
                state,
                fail_on_read=fail_on_history_read,
                fail_on_write=fail_on_history_write,
            ),
            events=MemoryMarketEventRepository(),
            generated_contents=MemoryGeneratedContentRepository(),
            publications=MemoryPublicationRepository(),
        ),
        state,
    )


def test_marketplace_pipeline_awaits_repository_save_and_comparison_reads() -> None:
    product = make_product()
    provider, state = make_provider(product=product)
    pipeline = make_pipeline(provider)

    result = run_async(pipeline.run("demo://ggsel"))
    stored_offers = run_async(provider.offers.list_all())

    assert state.offer_save_count == 1
    assert state.offer_list_count >= 2
    assert state.canonical_list_count == 1
    assert state.history_get_last_count == 1
    assert state.history_add_count == 1
    assert len(stored_offers) == 1
    assert len(result) == 1
    assert result[0].canonical_product == product
    assert result[0].status is ComparisonStatus.COMPLETE


def test_repository_backed_comparison_loads_data_before_pure_comparator() -> None:
    product = make_product()
    provider, state = make_provider(product=product)
    run_async(
        provider.offers.save(
            make_offer(marketplace="ggsel", price=Decimal("990")),
        ),
    )
    run_async(
        provider.offers.save(
            make_offer(
                marketplace="playerok",
                external_id="2001",
                price=Decimal("790"),
            ),
        ),
    )
    pipeline = make_pipeline(provider)

    result = run_async(pipeline.compare_repository_offers())

    assert state.offer_list_count == 1
    assert state.canonical_list_count == 1
    assert len(result) == 1
    assert result[0].best_offer is not None
    assert result[0].best_offer.offer.marketplace == "playerok"


def test_playerok_comparison_helpers_await_repository_backed_pipeline() -> None:
    product = make_product()
    provider, state = make_provider(product=product)
    ggsel_pipeline = make_pipeline(provider)
    playerok_pipeline = PlayerokPipeline(
        fetcher=cast(PlayerokFetcher, object()),
        extractor=PlayerokExtractor(),
        normalizer=PlayerokNormalizer(),
        comparison_pipeline=ggsel_pipeline,
    )
    run_async(
        provider.offers.save(
            make_offer(marketplace="ggsel", price=Decimal("990")),
        ),
    )
    run_async(
        provider.offers.save(
            make_offer(
                marketplace="playerok",
                external_id="2001",
                price=Decimal("790"),
            ),
        ),
    )

    result = run_async(playerok_pipeline.compare_repository_offers())

    assert state.offer_list_count == 1
    assert state.canonical_list_count == 1
    assert len(result) == 1
    assert result[0].status is ComparisonStatus.COMPLETE


def test_repository_save_errors_propagate_from_marketplace_pipeline() -> None:
    product = make_product()
    provider, state = make_provider(product=product, fail_on_offer_save=True)
    pipeline = make_pipeline(provider)

    with pytest.raises(RuntimeError, match="offer repository failed"):
        run_async(pipeline.run("demo://ggsel"))

    assert state.offer_save_count == 1
    assert state.offer_list_count == 0
    assert state.canonical_list_count == 0


@pytest.mark.parametrize(
    ("failure", "message"),
    (("read", "price history read failed"), ("write", "price history write failed")),
)
def test_price_history_errors_propagate_from_marketplace_pipeline(
    failure: str,
    message: str,
) -> None:
    product = make_product()
    provider, _ = make_provider(
        product=product,
        fail_on_history_read=failure == "read",
        fail_on_history_write=failure == "write",
    )
    pipeline = make_pipeline(provider)

    with pytest.raises(RuntimeError, match=message):
        run_async(pipeline.run("demo://ggsel"))


def test_first_snapshot_is_persisted_without_event() -> None:
    product = make_product()
    provider, _ = make_provider(product=product)
    snapshot = make_snapshot()
    content = RecordingContentGenerator()
    pipeline = make_pipeline(
        provider,
        snapshot_builder=SequencedSnapshotBuilder((snapshot,)),
        content_generator=content,
    )

    run_async(pipeline.run("demo://ggsel"))

    assert run_async(provider.price_history.get_history("ggsel", "1001")) == [snapshot]
    assert content.events == []


def test_price_decrease_persists_pending_event_without_content() -> None:
    product = make_product()
    provider, state = make_provider(product=product)
    now = datetime.now(UTC)
    previous = make_snapshot(
        price=Decimal("990"),
        collected_at=now - timedelta(minutes=1),
    )
    current = make_snapshot(price=Decimal("790"), collected_at=now)
    run_async(provider.price_history.add(previous))
    content = RecordingContentGenerator()
    detector = RecordingPriceChangeDetector()
    pipeline = make_pipeline(
        provider,
        snapshot_builder=SequencedSnapshotBuilder((current,)),
        content_generator=content,
        price_change_detector=detector,
    )

    run_async(pipeline.run("demo://ggsel"))

    assert run_async(provider.price_history.get_history("ggsel", "1001")) == [
        previous,
        current,
    ]
    assert detector.calls == [(previous, current)]
    assert state.history_get_last_count == 1
    assert state.history_add_count == 2
    assert content.events == []
    assert len(run_async(provider.events.list_pending(now, 10))) == 1


def test_price_increase_is_persisted_without_price_drop_event() -> None:
    product = make_product()
    provider, _ = make_provider(product=product)
    now = datetime.now(UTC)
    previous = make_snapshot(
        price=Decimal("790"),
        collected_at=now - timedelta(minutes=1),
    )
    current = make_snapshot(price=Decimal("990"), collected_at=now)
    run_async(provider.price_history.add(previous))
    content = RecordingContentGenerator()
    pipeline = make_pipeline(
        provider,
        snapshot_builder=SequencedSnapshotBuilder((current,)),
        content_generator=content,
    )

    run_async(pipeline.run("demo://ggsel"))

    assert run_async(provider.price_history.get_history("ggsel", "1001")) == [
        previous,
        current,
    ]
    assert content.events == []


def test_unchanged_price_with_new_timestamp_is_persisted_without_event() -> None:
    product = make_product()
    provider, _ = make_provider(product=product)
    now = datetime.now(UTC)
    previous = make_snapshot(collected_at=now - timedelta(minutes=1))
    current = make_snapshot(collected_at=now)
    run_async(provider.price_history.add(previous))
    content = RecordingContentGenerator()
    pipeline = make_pipeline(
        provider,
        snapshot_builder=SequencedSnapshotBuilder((current,)),
        content_generator=content,
    )

    run_async(pipeline.run("demo://ggsel"))

    assert run_async(provider.price_history.get_history("ggsel", "1001")) == [
        previous,
        current,
    ]
    assert content.events == []


def test_exact_duplicate_snapshot_is_suppressed_without_event() -> None:
    product = make_product()
    provider, _ = make_provider(product=product)
    snapshot = make_snapshot()
    run_async(provider.price_history.add(snapshot))
    content = RecordingContentGenerator()
    pipeline = make_pipeline(
        provider,
        snapshot_builder=SequencedSnapshotBuilder((snapshot,)),
        content_generator=content,
    )

    run_async(pipeline.run("demo://ggsel"))

    assert run_async(provider.price_history.get_history("ggsel", "1001")) == [snapshot]
    assert content.events == []


def test_out_of_order_snapshot_is_persisted_without_false_event() -> None:
    product = make_product()
    provider, _ = make_provider(product=product)
    now = datetime.now(UTC)
    latest = make_snapshot(price=Decimal("790"), collected_at=now)
    historical = make_snapshot(
        price=Decimal("690"),
        collected_at=now - timedelta(minutes=1),
    )
    run_async(provider.price_history.add(latest))
    content = RecordingContentGenerator()
    detector = RecordingPriceChangeDetector()
    pipeline = make_pipeline(
        provider,
        snapshot_builder=SequencedSnapshotBuilder((historical,)),
        content_generator=content,
        price_change_detector=detector,
    )

    run_async(pipeline.run("demo://ggsel"))

    assert run_async(provider.price_history.get_history("ggsel", "1001")) == [
        historical,
        latest,
    ]
    assert detector.calls == []
    assert content.events == []


def test_snapshot_validation_remains_visible_in_stage_reporting() -> None:
    product = make_product()
    provider, _ = make_provider(product=product)
    messages: list[str] = []
    pipeline = make_pipeline(
        provider,
        snapshot_builder=FailingSnapshotBuilder(),
        stage_reporter=messages,
    )

    run_async(pipeline.run("demo://ggsel"))

    assert "Skipped snapshots: 1" in messages
    assert run_async(provider.price_history.get_history("ggsel", "1001")) == []


def test_pipeline_constructor_has_no_standalone_price_history_dependency() -> None:
    signature = inspect.signature(MarketplacePipeline)

    assert "price_history" not in signature.parameters
