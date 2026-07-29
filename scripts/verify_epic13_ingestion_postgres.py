# ruff: noqa: E402
from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ai.fake_provider import FakeAIProvider
from app.analytics.price_change import PriceChangeDetector
from app.domain.events import PriceDropEvent
from app.domain.market_events import (
    EventAddResult,
    MarketEventCandidate,
    PriceDropMarketEvent,
    build_event_identity,
)
from app.domain.marketplace import Marketplace
from app.domain.price_snapshot import PriceSnapshot
from app.insights.scoring import EventScorer
from app.models.market_event_record import MarketEventRecord
from app.models.offer import Offer
from app.models.price_snapshot_record import PriceSnapshotRecord
from app.parsers.ggsel_extractor import GGSelExtractor
from app.parsers.ggsel_fetcher import GGSelFetcher
from app.parsers.models import ParsedOffer
from app.parsers.normalizers import OfferNormalizer
from app.repositories.postgres import (
    PostgresCanonicalProductRepository,
    PostgresMarketEventRepository,
    PostgresOfferRepository,
    PostgresPriceHistoryRepository,
)
from app.repositories.provider import RepositoryProvider, create_postgres_provider
from app.services.content_generator import ContentGenerator
from app.services.event_builder import EventBuilder
from app.services.marketplace_application_runner import (
    MarketplaceApplicationRunner,
)
from app.services.marketplace_pipeline import MarketplacePipeline
from app.services.repository_scope import RepositoryScopeFactory
from app.services.snapshot_builder import SnapshotBuilder

DATABASE_URL_ENV = "EPIC13_DATABASE_URL"
NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


class VerificationError(RuntimeError):
    """Raised when a live ingestion verification assertion fails."""


class Verification:
    """Print and count live PostgreSQL ingestion checks."""

    def __init__(self) -> None:
        self.passed = 0

    def check(self, label: str, condition: bool) -> None:
        """Record one passing condition or stop verification."""
        if not condition:
            raise VerificationError(label)
        self.passed += 1
        print(f"PASS: {label}")


class FixedSnapshotBuilder(SnapshotBuilder):
    """Build exact snapshots at a caller-selected UTC timestamp."""

    def __init__(self, collected_at: datetime) -> None:
        self._collected_at = collected_at

    def build(self, offer: ParsedOffer) -> PriceSnapshot:
        """Build one complete snapshot from universal offer fields."""
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
    """Capture post-commit compatibility events without external AI."""

    def __init__(self, *, fail: bool = False) -> None:
        super().__init__(FakeAIProvider())
        self.events: list[PriceDropEvent] = []
        self._fail = fail

    async def generate(self, event: PriceDropEvent) -> str:
        """Record the event and optionally simulate post-commit failure."""
        self.events.append(event)
        if self._fail:
            msg = "controlled content failure"
            raise RuntimeError(msg)
        return "verified content"


class AddThenFailEventRepository(PostgresMarketEventRepository):
    """Fail after event insertion but before the outer transaction commits."""

    async def add_idempotently(
        self,
        candidate: MarketEventCandidate,
    ) -> EventAddResult:
        """Insert through the real repository, then trigger rollback."""
        await super().add_idempotently(candidate)
        msg = "controlled transaction rollback"
        raise RuntimeError(msg)


def make_offer(
    *,
    marketplace: str = "ggsel",
    external_id: str = "verify-offer",
    price: Decimal,
) -> ParsedOffer:
    """Create one complete deterministic verification offer."""
    return ParsedOffer(
        marketplace=marketplace,
        external_id=external_id,
        title="Minecraft Premium",
        url=f"https://example.com/{marketplace}/{external_id}",
        price=price,
        currency="RUB",
        seller_name="Verification Seller",
    )


def make_runner(
    *,
    offer: ParsedOffer,
    collected_at: datetime,
    scope_factory: RepositoryScopeFactory,
    content_generator: RecordingContentGenerator | None = None,
) -> MarketplaceApplicationRunner:
    """Compose the active runner without network or alternate business logic."""

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
    return MarketplaceApplicationRunner(
        marketplace=Marketplace(offer.marketplace),
        ingestion=ingest,
        repository_scope_factory=scope_factory,
        pipeline=pipeline,
    )


def postgres_scope_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> RepositoryScopeFactory:
    """Create one shared-session transaction scope per runner execution."""

    @asynccontextmanager
    async def scope() -> AsyncIterator[RepositoryProvider]:
        async with session_factory() as session, session.begin():
            yield create_postgres_provider(session)

    return scope


def failing_scope_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> RepositoryScopeFactory:
    """Create a scope that triggers failure after real event insertion."""

    @asynccontextmanager
    async def scope() -> AsyncIterator[RepositoryProvider]:
        async with session_factory() as session, session.begin():
            provider = create_postgres_provider(session)
            provider.events = AddThenFailEventRepository(session)
            yield provider

    return scope


async def reset_database(engine: AsyncEngine) -> None:
    """Clear active verification tables in the isolated database."""
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE TABLE market_events, offers, price_snapshots "
                "RESTART IDENTITY CASCADE"
            )
        )


async def seed_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
    offer: ParsedOffer,
    collected_at: datetime,
) -> None:
    """Commit one baseline snapshot before a verified transition."""
    async with session_factory() as session, session.begin():
        provider = create_postgres_provider(session)
        await provider.price_history.add(
            FixedSnapshotBuilder(collected_at).build(offer)
        )


async def load_events(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[PriceDropMarketEvent]:
    """Load all durable events through the repository mapping boundary."""
    async with session_factory() as session:
        event_ids = (
            await session.execute(
                select(MarketEventRecord.id).order_by(MarketEventRecord.created_at)
            )
        ).scalars()
        repository = PostgresMarketEventRepository(session)
        events: list[PriceDropMarketEvent] = []
        for event_id in event_ids:
            event = await repository.get_by_id(event_id)
            if event is not None:
                events.append(event)
        return events


async def row_count(
    session_factory: async_sessionmaker[AsyncSession],
    table: type[MarketEventRecord] | type[PriceSnapshotRecord] | type[Offer],
) -> int:
    """Count rows in one active ingestion table."""
    async with session_factory() as session:
        result = await session.execute(select(func.count()).select_from(table))
        return int(result.scalar_one())


async def verify_shared_session(
    verification: Verification,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Confirm all PostgreSQL repositories share one scope session."""
    async with postgres_scope_factory(session_factory)() as provider:
        session_ids = {
            id(
                cast(
                    PostgresCanonicalProductRepository, provider.canonical_products
                )._session
            ),
            id(cast(PostgresOfferRepository, provider.offers)._session),
            id(cast(PostgresPriceHistoryRepository, provider.price_history)._session),
            id(cast(PostgresMarketEventRepository, provider.events)._session),
        }
    verification.check(
        "all ingestion repositories share one session", len(session_ids) == 1
    )


async def verify_ingestion(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify creation, identity, replay, and post-commit compatibility."""
    await reset_database(engine)
    scope_factory = postgres_scope_factory(session_factory)
    old_offer = make_offer(price=Decimal("990.00"))
    first = await make_runner(
        offer=old_offer,
        collected_at=NOW,
        scope_factory=scope_factory,
    ).run("verify://first")
    verification.check(
        "first snapshot creates no event",
        first.snapshots_persisted == 1 and first.events_created == 0,
    )

    content = RecordingContentGenerator()
    drop_runner = make_runner(
        offer=make_offer(price=Decimal("790.00")),
        collected_at=NOW + timedelta(minutes=1),
        scope_factory=scope_factory,
        content_generator=content,
    )
    drop = await drop_runner.run("verify://drop")
    events = await load_events(session_factory)
    verification.check(
        "price drop creates one durable event",
        drop.events_created == 1 and len(events) == 1,
    )
    verification.check(
        "event and exact snapshots commit together",
        await row_count(session_factory, PriceSnapshotRecord) == 2
        and events[0].previous_snapshot.collected_at == NOW
        and events[0].current_snapshot.collected_at == NOW + timedelta(minutes=1),
    )
    expected_identity = build_event_identity(
        event_type=events[0].event_type,
        marketplace=events[0].marketplace,
        external_id=events[0].external_id,
        previous_snapshot=events[0].previous_snapshot,
        current_snapshot=events[0].current_snapshot,
    )
    verification.check(
        "stored identity matches domain recomputation",
        events[0].identity_key == expected_identity.key,
    )
    replay = await drop_runner.run("verify://drop-replay")
    verification.check(
        "exact replay creates no duplicate event",
        replay.event_candidates_built == 0
        and await row_count(session_factory, MarketEventRecord) == 1,
    )
    verification.check(
        "post-commit adapter preserves price values",
        len(content.events) == 1
        and content.events[0].old_price == 990.0
        and content.events[0].new_price == 790.0,
    )


async def verify_rollback(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify event failure rolls back all writes from its ingestion run."""
    await reset_database(engine)
    old_offer = make_offer(external_id="rollback-offer", price=Decimal("990.00"))
    await seed_snapshot(session_factory, old_offer, NOW)
    try:
        await make_runner(
            offer=make_offer(
                external_id="rollback-offer",
                price=Decimal("790.00"),
            ),
            collected_at=NOW + timedelta(minutes=1),
            scope_factory=failing_scope_factory(session_factory),
        ).run("verify://rollback")
    except RuntimeError as exc:
        if str(exc) != "controlled transaction rollback":
            raise
    else:
        raise VerificationError("controlled rollback was not raised")

    verification.check(
        "event failure rolls back offer snapshot and event",
        await row_count(session_factory, Offer) == 0
        and await row_count(session_factory, PriceSnapshotRecord) == 1
        and await row_count(session_factory, MarketEventRecord) == 0,
    )


async def verify_marketplace_isolation(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify equal external IDs remain independent across marketplaces."""
    await reset_database(engine)
    scope_factory = postgres_scope_factory(session_factory)
    for marketplace in ("ggsel", "playerok"):
        baseline = make_offer(
            marketplace=marketplace,
            external_id="shared-id",
            price=Decimal("990.00"),
        )
        await seed_snapshot(session_factory, baseline, NOW)
        result = await make_runner(
            offer=make_offer(
                marketplace=marketplace,
                external_id="shared-id",
                price=Decimal("790.00"),
            ),
            collected_at=NOW + timedelta(minutes=1),
            scope_factory=scope_factory,
        ).run(f"verify://{marketplace}")
        verification.check(
            f"{marketplace} creates its independent event",
            result.events_created == 1,
        )
    events = await load_events(session_factory)
    verification.check(
        "same external ID is isolated by marketplace",
        len(events) == 2 and len({event.identity_key for event in events}) == 2,
    )


async def verify_content_failure(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify post-commit content failure cannot remove durable state."""
    await reset_database(engine)
    baseline = make_offer(price=Decimal("990.00"))
    await seed_snapshot(session_factory, baseline, NOW)
    result = await make_runner(
        offer=make_offer(price=Decimal("790.00")),
        collected_at=NOW + timedelta(minutes=1),
        scope_factory=postgres_scope_factory(session_factory),
        content_generator=RecordingContentGenerator(fail=True),
    ).run("verify://content-failure")
    verification.check(
        "content failure leaves event committed",
        result.events_created == 1
        and result.content_items_generated == 0
        and len(result.errors) == 1
        and await row_count(session_factory, MarketEventRecord) == 1,
    )


async def run_verification(database_url: str) -> None:
    """Run all focused live ingestion checks."""
    verification = Verification()
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await verify_shared_session(verification, session_factory)
        await verify_ingestion(verification, engine, session_factory)
        await verify_rollback(verification, engine, session_factory)
        await verify_marketplace_isolation(verification, engine, session_factory)
        await verify_content_failure(verification, engine, session_factory)
        await reset_database(engine)
        print(f"Checks passed: {verification.passed}")
        print("SUCCESS")
    finally:
        await engine.dispose()


def apply_migrations(database_url: str) -> None:
    """Apply project migrations to the guarded isolated database."""
    os.environ["DATABASE_URL"] = database_url
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "head")


def main() -> None:
    """Guard the target database, migrate it, and run verification."""
    database_url = os.getenv(DATABASE_URL_ENV)
    if not database_url:
        raise SystemExit(
            f"Set {DATABASE_URL_ENV} to an isolated PostgreSQL test database."
        )
    url = make_url(database_url)
    database_name = url.database or ""
    if url.get_backend_name() != "postgresql" or not database_name.startswith(
        "epic13_"
    ):
        raise SystemExit(
            f"{DATABASE_URL_ENV} must target an isolated epic13_* PostgreSQL database."
        )
    apply_migrations(database_url)
    asyncio.run(run_verification(database_url))


if __name__ == "__main__":
    main()
