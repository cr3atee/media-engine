from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Coroutine, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.ai.fake_provider import FakeAIProvider
from app.analytics.price_change import PriceChangeDetector
from app.database.metadata import get_metadata
from app.domain.events import PriceDropEvent
from app.domain.market_events import (
    EventAddResult,
    MarketEventCandidate,
    PriceDropMarketEvent,
)
from app.domain.marketplace import Marketplace
from app.domain.price_snapshot import PriceSnapshot
from app.insights.scoring import EventScorer
from app.models.generated_content_record import GeneratedContentRecord
from app.models.market_event_record import MarketEventRecord
from app.models.offer import Offer
from app.models.price_snapshot_record import PriceSnapshotRecord
from app.models.publication_record import PublicationRecord
from app.parsers.ggsel_extractor import GGSelExtractor
from app.parsers.ggsel_fetcher import GGSelFetcher
from app.parsers.models import ParsedOffer
from app.parsers.normalizers import OfferNormalizer
from app.repositories.postgres import PostgresMarketEventRepository
from app.repositories.provider import RepositoryProvider, create_postgres_provider
from app.services.content_generator import ContentGenerator
from app.services.event_builder import EventBuilder
from app.services.marketplace_application_runner import MarketplaceApplicationRunner
from app.services.marketplace_pipeline import MarketplacePipeline
from app.services.repository_scope import RepositoryScopeFactory
from app.services.snapshot_builder import SnapshotBuilder

DATABASE_URL = os.getenv("EPIC13_DATABASE_URL")
_ISOLATED_DATABASE = DATABASE_URL is not None and (
    make_url(DATABASE_URL).database or ""
).startswith("epic13_")
_SKIP_REASON = (
    "EPIC13_DATABASE_URL must target an isolated epic13_* PostgreSQL database"
)
_ENGINE: AsyncEngine | None = (
    create_async_engine(DATABASE_URL, poolclass=NullPool)
    if DATABASE_URL is not None and _ISOLATED_DATABASE
    else None
)
_SESSION_FACTORY: async_sessionmaker[AsyncSession] | None = (
    async_sessionmaker(_ENGINE, expire_on_commit=False) if _ENGINE is not None else None
)

pytestmark = pytest.mark.skipif(not _ISOLATED_DATABASE, reason=_SKIP_REASON)

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run async integration checks without a pytest async plugin."""
    return asyncio.run(awaitable)


class FixedSnapshotBuilder(SnapshotBuilder):
    """Build a deterministic snapshot for one integration run."""

    def __init__(self, collected_at: datetime) -> None:
        self._collected_at = collected_at

    def build(self, offer: ParsedOffer) -> PriceSnapshot:
        """Build a snapshot from required offer values at a fixed time."""
        if offer.external_id is None or offer.price is None or offer.currency is None:
            msg = "Offer is incomplete."
            raise ValueError(msg)
        return PriceSnapshot(
            marketplace=offer.marketplace,
            external_id=offer.external_id,
            price=offer.price,
            currency=offer.currency,
            collected_at=self._collected_at,
        )


class RecordingContentGenerator(ContentGenerator):
    """Record the legacy runtime event received after transaction commit."""

    def __init__(self, *, fail: bool = False) -> None:
        super().__init__(FakeAIProvider())
        self.events: list[PriceDropEvent] = []
        self._fail = fail

    async def generate(self, event: PriceDropEvent) -> str:
        """Record an event and optionally raise a controlled failure."""
        self.events.append(event)
        if self._fail:
            msg = "controlled content failure"
            raise RuntimeError(msg)
        return "generated"


class AddThenFailPostgresMarketEventRepository(PostgresMarketEventRepository):
    """Insert an event and fail before the caller-owned transaction commits."""

    async def add_idempotently(
        self,
        candidate: MarketEventCandidate,
    ) -> EventAddResult:
        """Delegate insertion, then raise to verify outer rollback."""
        await super().add_idempotently(candidate)
        msg = "controlled event persistence failure"
        raise RuntimeError(msg)


def make_offer(
    *,
    marketplace: str = "ggsel",
    price: Decimal = Decimal("790.00"),
) -> ParsedOffer:
    """Create one complete offer for active runner integration."""
    return ParsedOffer(
        marketplace=marketplace,
        external_id="shared-offer",
        title="Minecraft Premium",
        url=f"https://example.com/{marketplace}/shared-offer",
        price=price,
        currency="RUB",
        seller_name="Seller",
    )


def make_runner(
    *,
    offer: ParsedOffer,
    collected_at: datetime,
    scope_factory: RepositoryScopeFactory | None = None,
    content_generator: RecordingContentGenerator | None = None,
) -> MarketplaceApplicationRunner:
    """Compose the active application runner with deterministic ingestion."""

    async def ingest(url: str) -> Sequence[ParsedOffer]:
        del url
        return (offer,)

    pipeline = MarketplacePipeline(
        fetcher=cast(GGSelFetcher, object()),
        extractor=GGSelExtractor(),
        normalizer=OfferNormalizer(offer.marketplace),
        snapshot_builder=FixedSnapshotBuilder(collected_at),
        price_change_detector=PriceChangeDetector(),
        event_builder=EventBuilder(),
        event_scorer=EventScorer(),
        content_generator=content_generator or RecordingContentGenerator(),
    )
    marketplace = Marketplace(offer.marketplace)
    return MarketplaceApplicationRunner(
        marketplace=marketplace,
        ingestion=ingest,
        repository_scope_factory=scope_factory or postgres_scope_factory(),
        pipeline=pipeline,
    )


def test_price_drop_commits_one_pending_durable_event() -> None:
    run_async(reset_database())
    run_async(seed_snapshot(make_offer(price=Decimal("990.00")), NOW))
    content = RecordingContentGenerator()
    runner = make_runner(
        offer=make_offer(),
        collected_at=NOW + timedelta(minutes=1),
        content_generator=content,
    )

    result = run_async(runner.run("demo://ggsel"))
    stored = run_async(load_events())

    assert result.event_candidates_built == 1
    assert result.events_created == 1
    assert result.events_existing == 0
    assert result.events_scored == 0
    assert result.content_items_generated == 0
    assert result.event_ids == (stored[0].id,)
    assert stored[0].previous_snapshot.collected_at == NOW
    assert stored[0].current_snapshot.collected_at == NOW + timedelta(minutes=1)
    assert stored[0].payload.old_price == Decimal("990.00")
    assert stored[0].payload.new_price == Decimal("790.00")
    assert content.events == []


def test_repeated_exact_ingestion_does_not_duplicate_event() -> None:
    run_async(reset_database())
    run_async(seed_snapshot(make_offer(price=Decimal("990.00")), NOW))
    runner = make_runner(
        offer=make_offer(),
        collected_at=NOW + timedelta(minutes=1),
    )

    first = run_async(runner.run("demo://ggsel"))
    second = run_async(runner.run("demo://ggsel"))

    assert first.events_created == 1
    assert second.event_candidates_built == 0
    assert second.events_existing == 0
    assert run_async(row_count(MarketEventRecord)) == 1
    assert run_async(row_count(PriceSnapshotRecord)) == 2


def test_event_failure_rolls_back_offer_snapshot_and_event() -> None:
    run_async(reset_database())
    run_async(seed_snapshot(make_offer(price=Decimal("990.00")), NOW))

    with pytest.raises(RuntimeError, match="controlled event persistence failure"):
        run_async(
            make_runner(
                offer=make_offer(),
                collected_at=NOW + timedelta(minutes=1),
                scope_factory=failing_event_scope_factory(),
            ).run("demo://ggsel")
        )

    assert run_async(row_count(Offer)) == 0
    assert run_async(row_count(PriceSnapshotRecord)) == 1
    assert run_async(row_count(MarketEventRecord)) == 0


def test_ingestion_does_not_invoke_failing_content_generator() -> None:
    run_async(reset_database())
    run_async(seed_snapshot(make_offer(price=Decimal("990.00")), NOW))
    result = run_async(
        make_runner(
            offer=make_offer(),
            collected_at=NOW + timedelta(minutes=1),
            content_generator=RecordingContentGenerator(fail=True),
        ).run("demo://ggsel")
    )

    assert result.events_created == 1
    assert result.events_scored == 0
    assert result.content_items_generated == 0
    assert result.errors == ()
    assert run_async(row_count(MarketEventRecord)) == 1


def test_same_external_id_is_isolated_by_marketplace() -> None:
    run_async(reset_database())
    for marketplace in ("ggsel", "playerok"):
        run_async(
            seed_snapshot(
                make_offer(marketplace=marketplace, price=Decimal("990.00")),
                NOW,
            )
        )
        result = run_async(
            make_runner(
                offer=make_offer(marketplace=marketplace),
                collected_at=NOW + timedelta(minutes=1),
            ).run(f"demo://{marketplace}")
        )
        assert result.events_created == 1

    events = run_async(load_events())
    assert len(events) == 2
    assert {event.marketplace for event in events} == {"ggsel", "playerok"}
    assert len({event.identity_key for event in events}) == 2


async def reset_database() -> None:
    """Create metadata and clear active ingestion tables in dependency order."""
    async with engine().begin() as connection:
        await connection.run_sync(get_metadata().create_all)
        await connection.execute(delete(PublicationRecord))
        await connection.execute(delete(GeneratedContentRecord))
        await connection.execute(delete(MarketEventRecord))
        await connection.execute(delete(PriceSnapshotRecord))
        await connection.execute(delete(Offer))


async def seed_snapshot(offer: ParsedOffer, collected_at: datetime) -> None:
    """Commit one baseline snapshot through the real repository provider."""
    async with session_factory()() as session, session.begin():
        provider = create_postgres_provider(session)
        snapshot = FixedSnapshotBuilder(collected_at).build(offer)
        await provider.price_history.add(snapshot)


async def load_events() -> list[PriceDropMarketEvent]:
    """Load durable events in stable creation order through the repository."""
    async with session_factory()() as session:
        rows = (
            await session.execute(
                select(MarketEventRecord.id).order_by(MarketEventRecord.created_at)
            )
        ).scalars()
        repository = PostgresMarketEventRepository(session)
        events: list[PriceDropMarketEvent] = []
        for event_id in rows:
            event = await repository.get_by_id(event_id)
            if event is not None:
                events.append(event)
        return events


async def row_count(model: type[Any]) -> int:
    """Count persisted rows for one SQLAlchemy model."""
    async with session_factory()() as session:
        result = await session.execute(select(func.count()).select_from(model))
        return int(result.scalar_one())


def postgres_scope_factory() -> RepositoryScopeFactory:
    """Create a shared-session PostgreSQL scope for the integration runner."""

    @asynccontextmanager
    async def scope() -> AsyncIterator[RepositoryProvider]:
        async with session_factory()() as session, session.begin():
            yield create_postgres_provider(session)

    return scope


def failing_event_scope_factory() -> RepositoryScopeFactory:
    """Create a scope that fails after a real event INSERT."""

    @asynccontextmanager
    async def scope() -> AsyncIterator[RepositoryProvider]:
        async with session_factory()() as session, session.begin():
            provider = create_postgres_provider(session)
            provider.events = AddThenFailPostgresMarketEventRepository(session)
            yield provider

    return scope


def engine() -> AsyncEngine:
    """Return the guarded live integration engine."""
    if _ENGINE is None:
        raise RuntimeError(_SKIP_REASON)
    return _ENGINE


def session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the guarded live integration session factory."""
    if _SESSION_FACTORY is None:
        raise RuntimeError(_SKIP_REASON)
    return _SESSION_FACTORY


def teardown_module() -> None:
    """Dispose the optional live integration engine."""
    if _ENGINE is not None:
        run_async(_ENGINE.dispose())
