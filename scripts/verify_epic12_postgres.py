# ruff: noqa: E402
from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ai.provider import AIProvider
from app.analytics.price_change import PriceChangeDetector
from app.domain.marketplace import Marketplace
from app.domain.price_snapshot import PriceSnapshot
from app.insights.scoring import EventScorer
from app.models.canonical_product import CanonicalProduct
from app.models.canonical_product_record import CanonicalProductRecord
from app.models.offer import Offer
from app.models.price_snapshot_record import PriceSnapshotRecord
from app.parsers.ggsel_extractor import GGSelExtractor
from app.parsers.ggsel_fetcher import GGSelFetcher
from app.parsers.models import ParsedOffer
from app.parsers.normalizers import OfferNormalizer
from app.repositories.offers import OfferRepository
from app.repositories.postgres import (
    PostgresCanonicalProductRepository,
    PostgresOfferRepository,
    PostgresPriceHistoryRepository,
)
from app.repositories.price_history import PriceHistoryRepository
from app.repositories.provider import RepositoryProvider, create_postgres_provider
from app.scheduler.jobs import GGSELJob, JobExecutionState, PlayerokJob
from app.scheduler.service import SchedulerService
from app.services.content_generator import ContentGenerator
from app.services.event_builder import EventBuilder
from app.services.marketplace_application_runner import (
    MarketplaceApplicationRunner,
    MarketplaceRunResult,
)
from app.services.marketplace_pipeline import MarketplacePipeline
from app.services.repository_scope import RepositoryScopeFactory
from app.services.snapshot_builder import SnapshotBuilder

DATABASE_URL_ENV = "EPIC12_DATABASE_URL"
EXPECTED_REVISION = "0006_use_utc_timestamps"


class VerificationError(RuntimeError):
    """Raised when a live EPIC 12 verification assertion fails."""


class Verification:
    """Record and print deterministic live verification checks."""

    def __init__(self) -> None:
        self.passed = 0

    def check(self, label: str, condition: bool) -> None:
        """Record one successful condition or stop verification."""
        if not condition:
            raise VerificationError(label)
        self.passed += 1
        print(f"PASS: {label}")


class StaticIngestion:
    """Return deterministic prepared offers without marketplace HTTP."""

    def __init__(self, offers: Sequence[ParsedOffer]) -> None:
        self._offers = tuple(offers)

    async def __call__(self, url: str) -> Sequence[ParsedOffer]:
        """Return the configured offers."""
        return self._offers


class UnusedFetcher:
    """Fetcher placeholder for runner paths that inject prepared offers."""

    async def fetch_html(self, url: str) -> str:
        """Reject accidental HTTP use in deterministic verification."""
        raise VerificationError("HTTP must not run during deterministic verification")


class UnusedExtractor:
    """Extractor placeholder for runner paths that inject prepared offers."""

    def extract(self, html: str) -> list[object]:
        """Reject accidental extraction in deterministic verification."""
        raise VerificationError("Extraction must not run during verification")


class RecordingAIProvider(AIProvider):
    """Deterministic provider that can observe commit state or fail."""

    def __init__(
        self,
        *,
        fail: bool = False,
        commit_probe: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        self.fail = fail
        self.commit_probe = commit_probe
        self.calls = 0
        self.commit_visible = False

    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        """Return deterministic content after optionally checking persistence."""
        self.calls += 1
        if self.commit_probe is not None:
            self.commit_visible = await self.commit_probe()
        if self.fail:
            raise RuntimeError("controlled content failure")
        return "verified content"


class FixedSnapshotBuilder:
    """Return a fixed snapshot to make retry checks exact."""

    def __init__(self, snapshot: PriceSnapshot) -> None:
        self._snapshot = snapshot

    def build(self, offer: ParsedOffer) -> PriceSnapshot:
        """Return the configured deterministic snapshot."""
        return self._snapshot


class FailingPriceChangeDetector:
    """Raise during deterministic event processing."""

    def detect(
        self,
        previous: PriceSnapshot,
        current: PriceSnapshot,
    ) -> None:
        """Fail after repository writes have occurred."""
        raise RuntimeError("controlled deterministic event failure")


class FailingOfferRepository(OfferRepository):
    """Delegate offer operations and fail on a configured save call."""

    def __init__(self, delegate: OfferRepository, fail_on_call: int) -> None:
        self._delegate = delegate
        self._fail_on_call = fail_on_call
        self._calls = 0

    async def save(self, offer: ParsedOffer) -> None:
        """Save until the controlled failure point is reached."""
        self._calls += 1
        if self._calls == self._fail_on_call:
            raise RuntimeError("controlled offer write failure")
        await self._delegate.save(offer)

    async def get_by_identity(
        self,
        marketplace: str,
        external_id: str,
    ) -> ParsedOffer | None:
        """Delegate identity lookup."""
        return await self._delegate.get_by_identity(marketplace, external_id)

    async def list_by_marketplace(self, marketplace: str) -> Sequence[ParsedOffer]:
        """Delegate marketplace lookup."""
        return await self._delegate.list_by_marketplace(marketplace)

    async def list_all(self) -> Sequence[ParsedOffer]:
        """Delegate complete lookup."""
        return await self._delegate.list_all()


class FailingPriceHistoryRepository(PriceHistoryRepository):
    """Delegate reads and fail every snapshot write."""

    def __init__(self, delegate: PriceHistoryRepository) -> None:
        self._delegate = delegate

    async def add(self, snapshot: PriceSnapshot) -> bool:
        """Raise at the controlled snapshot write boundary."""
        raise RuntimeError("controlled snapshot write failure")

    async def get_last(
        self,
        marketplace: str,
        external_id: str,
    ) -> PriceSnapshot | None:
        """Delegate latest lookup."""
        return await self._delegate.get_last(marketplace, external_id)

    async def get_previous(
        self,
        marketplace: str,
        external_id: str,
    ) -> PriceSnapshot | None:
        """Delegate previous lookup."""
        return await self._delegate.get_previous(marketplace, external_id)

    async def get_history(
        self,
        marketplace: str,
        external_id: str,
    ) -> list[PriceSnapshot]:
        """Delegate history lookup."""
        return await self._delegate.get_history(marketplace, external_id)


class FailOnceRunner:
    """Fail once before delegating to the real application runner."""

    def __init__(self, delegate: MarketplaceApplicationRunner) -> None:
        self._delegate = delegate
        self.calls = 0

    async def run(self, url: str) -> MarketplaceRunResult:
        """Fail the first call and run the real application thereafter."""
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("controlled scheduler failure")
        return await self._delegate.run(url)


class AlwaysFailRunner:
    """Fail every call for scheduler failure-statistics verification."""

    async def run(self, url: str) -> None:
        """Raise a deterministic runner failure."""
        raise RuntimeError("controlled permanent scheduler failure")


class ScopeState:
    """Track repository scope entries and sessions for verification."""

    def __init__(self) -> None:
        self.entries = 0
        self.sessions: list[AsyncSession] = []


type ProviderDecorator = Callable[[RepositoryProvider], RepositoryProvider]


def make_offer(
    *,
    marketplace: str = "ggsel",
    external_id: str | None = "offer-1",
    title: str | None = "Minecraft Premium",
    price: Decimal | None = Decimal("790.12"),
    currency: str | None = "RUB",
    canonical_product_id: UUID | None = None,
) -> ParsedOffer:
    """Build a deterministic parsed offer for live checks."""
    suffix = external_id or "anonymous"
    return ParsedOffer(
        marketplace=marketplace,
        external_id=external_id,
        title=title,
        url=f"https://example.com/{marketplace}/{suffix}",
        price=price,
        currency=currency,
        seller_id=f"{marketplace}-seller",
        seller_name=f"{marketplace} Seller",
        canonical_product_id=canonical_product_id,
    )


def make_snapshot(
    *,
    marketplace: str = "ggsel",
    external_id: str = "offer-1",
    price: Decimal = Decimal("790.12"),
    collected_at: datetime | None = None,
) -> PriceSnapshot:
    """Build a deterministic UTC price snapshot for live checks."""
    return PriceSnapshot(
        marketplace=marketplace,
        external_id=external_id,
        price=price,
        currency="RUB",
        collected_at=collected_at or datetime.now(UTC),
    )


def make_scope_factory(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    decorator: ProviderDecorator | None = None,
    state: ScopeState | None = None,
    force_commit_failure: bool = False,
) -> RepositoryScopeFactory:
    """Create a PostgreSQL scope with optional verification-only injection."""

    @asynccontextmanager
    async def repository_scope() -> AsyncIterator[RepositoryProvider]:
        async with session_factory() as session:
            if state is not None:
                state.entries += 1
                state.sessions.append(session)
            async with session.begin():
                provider = create_postgres_provider(session)
                if decorator is not None:
                    provider = decorator(provider)
                yield provider
                if force_commit_failure:
                    await session.execute(
                        text(
                            "INSERT INTO epic12_commit_failure_probe (value) "
                            "VALUES (1), (1)"
                        )
                    )

    return repository_scope


def make_pipeline(
    *,
    snapshot: PriceSnapshot,
    ai_provider: RecordingAIProvider | None = None,
    detector: PriceChangeDetector | None = None,
) -> MarketplacePipeline:
    """Compose the existing pipeline for deterministic runner verification."""
    provider = ai_provider or RecordingAIProvider()
    return MarketplacePipeline(
        fetcher=cast(GGSelFetcher, UnusedFetcher()),
        extractor=cast(GGSelExtractor, UnusedExtractor()),
        normalizer=OfferNormalizer("ggsel"),
        snapshot_builder=cast(SnapshotBuilder, FixedSnapshotBuilder(snapshot)),
        price_change_detector=detector or PriceChangeDetector(),
        event_builder=EventBuilder(),
        event_scorer=EventScorer(),
        content_generator=ContentGenerator(provider),
    )


def make_runner(
    *,
    offers: Sequence[ParsedOffer],
    snapshot: PriceSnapshot,
    session_factory: async_sessionmaker[AsyncSession],
    ai_provider: RecordingAIProvider | None = None,
    detector: PriceChangeDetector | None = None,
    decorator: ProviderDecorator | None = None,
    scope_state: ScopeState | None = None,
    force_commit_failure: bool = False,
) -> MarketplaceApplicationRunner:
    """Compose a real PostgreSQL-backed application runner."""
    return MarketplaceApplicationRunner(
        marketplace=Marketplace.GGSEL,
        ingestion=StaticIngestion(offers),
        repository_scope_factory=make_scope_factory(
            session_factory,
            decorator=decorator,
            state=scope_state,
            force_commit_failure=force_commit_failure,
        ),
        pipeline=make_pipeline(
            snapshot=snapshot,
            ai_provider=ai_provider,
            detector=detector,
        ),
    )


async def reset_runtime(engine: AsyncEngine) -> None:
    """Reset only EPIC 12 active tables in the guarded test database."""
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE TABLE offers, price_snapshots, canonical_products "
                "RESTART IDENTITY CASCADE"
            )
        )
        await connection.execute(
            text("DROP TABLE IF EXISTS epic12_commit_failure_probe")
        )


async def count_rows(
    session_factory: async_sessionmaker[AsyncSession],
    model: type[Offer] | type[PriceSnapshotRecord] | type[CanonicalProductRecord],
) -> int:
    """Count persisted rows for one active persistence model."""
    async with session_factory() as session:
        result = await session.execute(select(func.count()).select_from(model))
        return int(result.scalar_one())


async def seed_product_and_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
    product: CanonicalProduct,
    snapshot: PriceSnapshot,
) -> None:
    """Persist a canonical product and one baseline snapshot."""
    async with session_factory() as session, session.begin():
        provider = create_postgres_provider(session)
        await provider.canonical_products.save(product)
        await provider.price_history.add(snapshot)


async def verify_environment(
    verification: Verification,
    engine: AsyncEngine,
) -> None:
    """Verify PostgreSQL, revision, constraints, indexes, and UTC columns."""
    print("\n=== ENVIRONMENT AND SCHEMA ===")
    async with engine.connect() as connection:
        database, version = (
            await connection.execute(
                text("SELECT current_database(), current_setting('server_version')")
            )
        ).one()
        revision = (
            await connection.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar_one()
        index_names = set(
            (
                await connection.execute(
                    text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
                )
            ).scalars()
        )
        constraints = {
            row.conname: row.definition
            for row in (
                await connection.execute(
                    text(
                        "SELECT conname, pg_get_constraintdef(oid) AS definition "
                        "FROM pg_constraint "
                        "WHERE conname IN ("
                        "'uq_price_snapshots_exact_identity', "
                        "'fk_offers_canonical_product_id_canonical_products')"
                    )
                )
            )
        }
        timestamp_columns = {
            (row.table_name, row.column_name): row.data_type
            for row in (
                await connection.execute(
                    text(
                        "SELECT table_name, column_name, data_type "
                        "FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND ("
                        "(table_name = 'offers' AND column_name = 'created_at') OR "
                        "(table_name = 'canonical_products' "
                        "AND column_name = 'created_at') OR "
                        "(table_name = 'price_snapshots' "
                        "AND column_name = 'collected_at'))"
                    )
                )
            )
        }

    print(f"Database: {database}")
    print(f"PostgreSQL: {version}")
    print(f"Alembic revision: {revision}")
    verification.check(
        "isolated verification database", str(database).startswith("epic12_")
    )
    verification.check("expected Alembic revision", revision == EXPECTED_REVISION)
    for index_name in (
        "uq_offers_marketplace_external_id_not_null",
        "ix_offers_canonical_product_id",
        "ix_price_snapshots_history_order",
    ):
        verification.check(f"index {index_name}", index_name in index_names)
    verification.check(
        "snapshot exact-identity constraint",
        "uq_price_snapshots_exact_identity" in constraints,
    )
    foreign_key = constraints.get(
        "fk_offers_canonical_product_id_canonical_products",
        "",
    )
    verification.check("canonical product foreign key", "FOREIGN KEY" in foreign_key)
    verification.check(
        "canonical delete sets offer reference null",
        "ON DELETE SET NULL" in foreign_key,
    )
    verification.check(
        "active timestamps are timezone-aware",
        all(value == "timestamp with time zone" for value in timestamp_columns.values())
        and len(timestamp_columns) == 3,
    )


async def verify_offer_repository(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify offer mapping, upsert semantics, isolation, and concurrency."""
    print("\n=== OFFER REPOSITORY ===")
    await reset_runtime(engine)
    first_product = CanonicalProduct(uuid4(), "Minecraft", "games", ("mc",))
    second_product = CanonicalProduct(uuid4(), "Minecraft Java", "games", ("mcj",))
    original = make_offer(canonical_product_id=first_product.id)

    async with session_factory() as session, session.begin():
        provider = create_postgres_provider(session)
        await provider.canonical_products.save(first_product)
        await provider.canonical_products.save(second_product)
        await provider.offers.save(original)

    async with session_factory() as session, session.begin():
        repository = PostgresOfferRepository(session)
        stored = await repository.get_by_identity("ggsel", "offer-1")
        verification.check("initial offer inserted", stored is not None)
        verification.check(
            "Decimal price preserved",
            stored is not None and stored.price == Decimal("790.12"),
        )
        incoming = ParsedOffer(
            marketplace="ggsel",
            external_id="offer-1",
            title="Minecraft Java Updated",
            url=None,
            price=Decimal("789.99"),
            currency=None,
            seller_id=None,
            seller_name="Updated Seller",
            canonical_product_id=second_product.id,
        )
        await repository.save(incoming)
        await repository.save(make_offer(marketplace="playerok"))
        await repository.save(make_offer(external_id=None, title="Anonymous one"))
        await repository.save(make_offer(external_id=None, title="Anonymous two"))

    async with session_factory() as session:
        repository = PostgresOfferRepository(session)
        updated = await repository.get_by_identity("ggsel", "offer-1")
        offers = tuple(await repository.list_all())
        verification.check("stable identity upserts to one row", len(offers) == 4)
        verification.check(
            "upsert updates mutable values",
            updated is not None
            and updated.title == "Minecraft Java Updated"
            and updated.price == Decimal("789.99")
            and updated.seller_name == "Updated Seller",
        )
        verification.check(
            "incoming None preserves meaningful values",
            updated is not None
            and updated.url == original.url
            and updated.currency == original.currency
            and updated.seller_id == original.seller_id,
        )
        verification.check(
            "canonical product reference updates",
            updated is not None and updated.canonical_product_id == second_product.id,
        )
        verification.check(
            "same external ID is isolated by marketplace",
            sum(offer.external_id == "offer-1" for offer in offers) == 2,
        )
        verification.check(
            "null external IDs remain append-only",
            sum(offer.external_id is None for offer in offers) == 2,
        )

    first_inserted = asyncio.Event()
    second_started = asyncio.Event()

    async def first_writer() -> None:
        async with session_factory() as session, session.begin():
            repository = PostgresOfferRepository(session)
            await repository.save(
                make_offer(external_id="concurrent", title="First writer")
            )
            first_inserted.set()
            await second_started.wait()
            await asyncio.sleep(0.05)

    async def second_writer() -> None:
        await first_inserted.wait()
        async with session_factory() as session, session.begin():
            second_started.set()
            repository = PostgresOfferRepository(session)
            await repository.save(
                make_offer(external_id="concurrent", title="Second writer")
            )
            await session.execute(text("SELECT 1"))

    await asyncio.gather(first_writer(), second_writer())
    async with session_factory() as session:
        repository = PostgresOfferRepository(session)
        concurrent = await repository.get_by_identity("ggsel", "concurrent")
        concurrent_count = (
            await session.execute(
                select(func.count())
                .select_from(Offer)
                .where(Offer.marketplace == "ggsel", Offer.external_id == "concurrent")
            )
        ).scalar_one()
    verification.check(
        "two-session offer upsert leaves one logical row", concurrent_count == 1
    )
    verification.check(
        "waiting writer deterministically updates final values",
        concurrent is not None and concurrent.title == "Second writer",
    )


async def verify_snapshot_repository(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify snapshot conflicts, ordering, isolation, and concurrency."""
    print("\n=== PRICE HISTORY REPOSITORY ===")
    await reset_runtime(engine)
    base_time = datetime(2026, 7, 29, 10, 0, tzinfo=UTC)
    exact = make_snapshot(external_id="exact", collected_at=base_time)

    async with session_factory() as session, session.begin():
        repository = PostgresPriceHistoryRepository(session)
        first = await repository.add(exact)
        second = await repository.add(exact)
        transaction_probe = (await session.execute(text("SELECT 1"))).scalar_one()
    verification.check("first exact snapshot insert reports True", first)
    verification.check("second exact snapshot insert reports False", not second)
    verification.check(
        "suppressed conflict leaves transaction usable", transaction_probe == 1
    )

    same_time_low = make_snapshot(
        external_id="same-time",
        price=Decimal("790.00"),
        collected_at=base_time,
    )
    same_time_high = make_snapshot(
        external_id="same-time",
        price=Decimal("990.00"),
        collected_at=base_time,
    )
    same_price_later = make_snapshot(
        external_id="same-price",
        price=Decimal("790.00"),
        collected_at=base_time + timedelta(minutes=1),
    )
    same_price_earlier = make_snapshot(
        external_id="same-price",
        price=Decimal("790.00"),
        collected_at=base_time,
    )
    latest = make_snapshot(
        external_id="ordered",
        price=Decimal("700.00"),
        collected_at=base_time + timedelta(minutes=2),
    )
    earliest = make_snapshot(
        external_id="ordered",
        price=Decimal("900.00"),
        collected_at=base_time,
    )
    middle = make_snapshot(
        external_id="ordered",
        price=Decimal("800.00"),
        collected_at=base_time + timedelta(minutes=1),
    )
    async with session_factory() as session, session.begin():
        repository = PostgresPriceHistoryRepository(session)
        for snapshot in (
            same_time_low,
            same_time_high,
            same_price_earlier,
            same_price_later,
            latest,
            earliest,
            middle,
            make_snapshot(
                marketplace="playerok",
                external_id="ordered",
                collected_at=base_time,
            ),
        ):
            verification.check(
                "non-identical snapshot inserted", await repository.add(snapshot)
            )

    async with session_factory() as session:
        repository = PostgresPriceHistoryRepository(session)
        same_time_history = await repository.get_history("ggsel", "same-time")
        same_price_history = await repository.get_history("ggsel", "same-price")
        ordered = await repository.get_history("ggsel", "ordered")
        previous = await repository.get_previous("ggsel", "ordered")
        current = await repository.get_last("ggsel", "ordered")
        playerok = await repository.get_history("playerok", "ordered")
    verification.check(
        "same timestamp with different price persists", len(same_time_history) == 2
    )
    verification.check(
        "record ID breaks equal timestamp ties",
        same_time_history == [same_time_low, same_time_high],
    )
    verification.check(
        "same price with new timestamp persists",
        same_price_history == [same_price_earlier, same_price_later],
    )
    verification.check(
        "out-of-order writes return chronologically",
        ordered == [earliest, middle, latest],
    )
    verification.check("latest snapshot semantics", current == latest)
    verification.check("previous snapshot semantics", previous == middle)
    verification.check(
        "snapshot histories isolate marketplaces",
        playerok[0].marketplace == "playerok" and len(playerok) == 1,
    )

    first_inserted = asyncio.Event()
    second_started = asyncio.Event()
    concurrent_snapshot = make_snapshot(
        external_id="concurrent-exact",
        collected_at=base_time,
    )
    insert_results: list[bool] = []

    async def first_writer() -> None:
        async with session_factory() as session, session.begin():
            repository = PostgresPriceHistoryRepository(session)
            insert_results.append(await repository.add(concurrent_snapshot))
            first_inserted.set()
            await second_started.wait()
            await asyncio.sleep(0.05)

    async def second_writer() -> None:
        await first_inserted.wait()
        async with session_factory() as session, session.begin():
            second_started.set()
            repository = PostgresPriceHistoryRepository(session)
            insert_results.append(await repository.add(concurrent_snapshot))
            await session.execute(text("SELECT 1"))

    await asyncio.gather(first_writer(), second_writer())
    async with session_factory() as session:
        history = await PostgresPriceHistoryRepository(session).get_history(
            "ggsel",
            "concurrent-exact",
        )
    verification.check("concurrent exact snapshot leaves one row", len(history) == 1)
    verification.check(
        "concurrent exact snapshot reports insert and suppression",
        sorted(insert_results) == [False, True],
    )

    different_results = await asyncio.gather(
        _insert_snapshot(
            session_factory,
            make_snapshot(
                external_id="concurrent-distinct",
                price=Decimal("700.00"),
                collected_at=base_time,
            ),
        ),
        _insert_snapshot(
            session_factory,
            make_snapshot(
                external_id="concurrent-distinct",
                price=Decimal("800.00"),
                collected_at=base_time,
            ),
        ),
    )
    verification.check(
        "concurrent non-identical snapshots both persist", all(different_results)
    )


async def _insert_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
    snapshot: PriceSnapshot,
) -> bool:
    async with session_factory() as session, session.begin():
        return await PostgresPriceHistoryRepository(session).add(snapshot)


async def verify_foreign_key(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify canonical-product reference enforcement and delete behavior."""
    print("\n=== CANONICAL PRODUCT FOREIGN KEY ===")
    await reset_runtime(engine)
    product = CanonicalProduct(uuid4(), "Minecraft", "games", ())
    valid = make_offer(external_id="valid-fk", canonical_product_id=product.id)
    nullable = make_offer(external_id="nullable-fk", canonical_product_id=None)
    async with session_factory() as session, session.begin():
        provider = create_postgres_provider(session)
        await provider.canonical_products.save(product)
        await provider.offers.save(valid)
        await provider.offers.save(nullable)
    verification.check(
        "valid and nullable canonical references persist",
        await count_rows(session_factory, Offer) == 2,
    )

    invalid_rejected = False
    try:
        async with session_factory() as session, session.begin():
            await PostgresOfferRepository(session).save(
                make_offer(external_id="invalid-fk", canonical_product_id=uuid4())
            )
    except IntegrityError:
        invalid_rejected = True
    verification.check("invalid canonical reference is rejected", invalid_rejected)
    verification.check(
        "invalid FK transaction leaves no offer",
        await count_rows(session_factory, Offer) == 2,
    )

    async with session_factory() as session, session.begin():
        await session.execute(
            text("DELETE FROM canonical_products WHERE id = :product_id"),
            {"product_id": product.id},
        )
    async with session_factory() as session:
        stored = await PostgresOfferRepository(session).get_by_identity(
            "ggsel", "valid-fk"
        )
    verification.check("deleting canonical product preserves offer", stored is not None)
    verification.check(
        "deleting canonical product sets reference null",
        stored is not None and stored.canonical_product_id is None,
    )


async def verify_scope_ownership(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify shared session ownership, commit visibility, and rollback."""
    print("\n=== SHARED SESSION AND SCOPE OWNERSHIP ===")
    await reset_runtime(engine)
    scope = make_scope_factory(session_factory)
    product = CanonicalProduct(uuid4(), "Shared session", None, ())
    async with scope() as provider:
        session_ids = {
            id(
                cast(
                    PostgresCanonicalProductRepository, provider.canonical_products
                )._session
            ),
            id(cast(PostgresOfferRepository, provider.offers)._session),
            id(cast(PostgresPriceHistoryRepository, provider.price_history)._session),
        }
        await provider.canonical_products.save(product)
        verification.check(
            "all repositories receive one AsyncSession", len(session_ids) == 1
        )
        verification.check(
            "repository does not commit before scope exit",
            await count_rows(session_factory, CanonicalProductRecord) == 0,
        )
    verification.check(
        "scope commits on successful exit",
        await count_rows(session_factory, CanonicalProductRecord) == 1,
    )

    rolled_back = CanonicalProduct(uuid4(), "Rolled back", None, ())
    try:
        async with scope() as provider:
            await provider.canonical_products.save(rolled_back)
            raise RuntimeError("controlled scope rollback")
    except RuntimeError:
        pass
    async with session_factory() as session:
        missing = await PostgresCanonicalProductRepository(session).get_by_id(
            rolled_back.id
        )
    verification.check("scope rolls back on exception", missing is None)


async def verify_runner_transactions(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify runner commit, rollback, commit failure, and content failure."""
    print("\n=== APPLICATION RUNNER TRANSACTIONS ===")
    await reset_runtime(engine)
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    product = CanonicalProduct(uuid4(), "Minecraft Premium", "games", ("minecraft",))
    previous = make_snapshot(
        price=Decimal("990.00"), collected_at=now - timedelta(minutes=1)
    )
    current = make_snapshot(price=Decimal("790.00"), collected_at=now)
    offer = make_offer(price=current.price, canonical_product_id=product.id)
    await seed_product_and_snapshot(session_factory, product, previous)

    async def commit_visible() -> bool:
        return (
            await count_rows(session_factory, Offer) == 1
            and await count_rows(session_factory, PriceSnapshotRecord) == 2
        )

    ai_provider = RecordingAIProvider(commit_probe=commit_visible)
    runner = make_runner(
        offers=(offer,),
        snapshot=current,
        session_factory=session_factory,
        ai_provider=ai_provider,
    )
    commits = 0

    def record_commit(session: Session) -> None:
        nonlocal commits
        commits += 1

    event.listen(Session, "after_commit", record_commit)
    try:
        result = await runner.run("verify://ggsel")
    finally:
        event.remove(Session, "after_commit", record_commit)

    verification.check("runner transaction commits exactly once", commits == 1)
    verification.check(
        "runner reports committed persistence", result.persistence_committed
    )
    verification.check(
        "runner result counts match persisted work",
        result.offers_persisted == 1
        and result.snapshots_persisted == 1
        and result.events_created == 1,
    )
    verification.check(
        "post-commit content observes committed rows",
        ai_provider.commit_visible and ai_provider.calls == 1,
    )
    result_values = (getattr(result, field.name) for field in fields(result))
    verification.check(
        "runner result exposes no SQLAlchemy session",
        not any(isinstance(value, AsyncSession) for value in result_values),
    )

    await reset_runtime(engine)
    two_offers = (make_offer(external_id="one"), make_offer(external_id="two"))

    def fail_offer(provider: RepositoryProvider) -> RepositoryProvider:
        provider.offers = FailingOfferRepository(provider.offers, 2)
        return provider

    offer_failure_ai = RecordingAIProvider()
    offer_failure = make_runner(
        offers=two_offers,
        snapshot=current,
        session_factory=session_factory,
        ai_provider=offer_failure_ai,
        decorator=fail_offer,
    )
    failed = False
    try:
        await offer_failure.run("verify://offer-failure")
    except RuntimeError as exc:
        failed = "offer write failure" in str(exc)
    verification.check("offer write failure propagates", failed)
    verification.check(
        "offer write failure rolls back all offers",
        await count_rows(session_factory, Offer) == 0,
    )
    verification.check(
        "offer write failure persists no snapshots",
        await count_rows(session_factory, PriceSnapshotRecord) == 0,
    )
    verification.check(
        "offer write failure skips post-commit content", offer_failure_ai.calls == 0
    )

    await reset_runtime(engine)

    def fail_snapshot(provider: RepositoryProvider) -> RepositoryProvider:
        provider.price_history = FailingPriceHistoryRepository(provider.price_history)
        return provider

    snapshot_failure_ai = RecordingAIProvider()
    offer_without_product = make_offer(price=current.price)
    snapshot_failure = make_runner(
        offers=(offer_without_product,),
        snapshot=current,
        session_factory=session_factory,
        ai_provider=snapshot_failure_ai,
        decorator=fail_snapshot,
    )
    failed = False
    try:
        await snapshot_failure.run("verify://snapshot-failure")
    except RuntimeError as exc:
        failed = "snapshot write failure" in str(exc)
    verification.check("snapshot write failure propagates", failed)
    verification.check(
        "snapshot failure rolls back offer",
        await count_rows(session_factory, Offer) == 0,
    )
    verification.check(
        "snapshot failure leaves no snapshot",
        await count_rows(session_factory, PriceSnapshotRecord) == 0,
    )
    verification.check(
        "snapshot failure skips post-commit content", snapshot_failure_ai.calls == 0
    )

    await reset_runtime(engine)
    await seed_product_and_snapshot(session_factory, product, previous)
    event_failure_ai = RecordingAIProvider()
    event_failure = make_runner(
        offers=(offer,),
        snapshot=current,
        session_factory=session_factory,
        ai_provider=event_failure_ai,
        detector=cast(PriceChangeDetector, FailingPriceChangeDetector()),
    )
    failed = False
    try:
        await event_failure.run("verify://event-failure")
    except RuntimeError as exc:
        failed = "deterministic event failure" in str(exc)
    verification.check("deterministic event failure propagates", failed)
    verification.check(
        "event failure rolls back offer", await count_rows(session_factory, Offer) == 0
    )
    verification.check(
        "event failure rolls back current snapshot",
        await count_rows(session_factory, PriceSnapshotRecord) == 1,
    )
    verification.check(
        "event failure skips post-commit content", event_failure_ai.calls == 0
    )

    await reset_runtime(engine)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "CREATE TABLE epic12_commit_failure_probe ("
                "value INTEGER, "
                "CONSTRAINT uq_epic12_commit_probe UNIQUE (value) "
                "DEFERRABLE INITIALLY DEFERRED)"
            )
        )
    commit_failure_ai = RecordingAIProvider()
    commit_scope_state = ScopeState()
    commit_failure = make_runner(
        offers=(offer_without_product,),
        snapshot=current,
        session_factory=session_factory,
        ai_provider=commit_failure_ai,
        scope_state=commit_scope_state,
        force_commit_failure=True,
    )
    failed = False
    try:
        await commit_failure.run("verify://commit-failure")
    except IntegrityError:
        failed = True
    verification.check("database-level commit failure propagates", failed)
    verification.check(
        "commit failure rolls back application writes",
        await count_rows(session_factory, Offer) == 0
        and await count_rows(session_factory, PriceSnapshotRecord) == 0,
    )
    verification.check(
        "commit failure skips post-commit content", commit_failure_ai.calls == 0
    )
    verification.check(
        "failed commit leaves session without transaction",
        len(commit_scope_state.sessions) == 1
        and not commit_scope_state.sessions[0].in_transaction(),
    )

    await reset_runtime(engine)
    await seed_product_and_snapshot(session_factory, product, previous)
    content_failure_ai = RecordingAIProvider(fail=True)
    content_failure = make_runner(
        offers=(offer,),
        snapshot=current,
        session_factory=session_factory,
        ai_provider=content_failure_ai,
    )
    content_result = await content_failure.run("verify://content-failure")
    verification.check(
        "content failure occurs after successful commit",
        content_result.persistence_committed and len(content_result.errors) == 1,
    )
    verification.check(
        "content failure preserves offer and snapshots",
        await count_rows(session_factory, Offer) == 1
        and await count_rows(session_factory, PriceSnapshotRecord) == 2,
    )


async def verify_retries(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify retries after rollback, success, and post-commit failure."""
    print("\n=== RETRY BEHAVIOR ===")
    await reset_runtime(engine)
    now = datetime(2026, 7, 29, 13, 0, tzinfo=UTC)
    product = CanonicalProduct(uuid4(), "Minecraft Premium", "games", ())
    previous = make_snapshot(
        price=Decimal("990.00"), collected_at=now - timedelta(minutes=1)
    )
    current = make_snapshot(price=Decimal("790.00"), collected_at=now)
    offer = make_offer(price=current.price, canonical_product_id=product.id)
    await seed_product_and_snapshot(session_factory, product, previous)

    def fail_first_offer(provider: RepositoryProvider) -> RepositoryProvider:
        provider.offers = FailingOfferRepository(provider.offers, 1)
        return provider

    failed_runner = make_runner(
        offers=(offer,),
        snapshot=current,
        session_factory=session_factory,
        decorator=fail_first_offer,
    )
    try:
        await failed_runner.run("verify://retry-rollback")
    except RuntimeError:
        pass
    retry_ai = RecordingAIProvider()
    retry_runner = make_runner(
        offers=(offer,),
        snapshot=current,
        session_factory=session_factory,
        ai_provider=retry_ai,
    )
    retry_result = await retry_runner.run("verify://retry-rollback")
    verification.check(
        "retry after rollback succeeds",
        retry_result.persistence_committed and retry_result.events_created == 1,
    )
    verification.check(
        "retry after rollback persists one logical offer",
        await count_rows(session_factory, Offer) == 1,
    )

    repeated = await retry_runner.run("verify://retry-success")
    verification.check(
        "retry after success upserts offer",
        await count_rows(session_factory, Offer) == 1,
    )
    verification.check(
        "retry after success suppresses exact snapshot",
        repeated.snapshots_persisted == 0,
    )
    verification.check(
        "retry after success creates no false event",
        repeated.events_created == 0 and repeated.content_items_generated == 0,
    )

    await reset_runtime(engine)
    await seed_product_and_snapshot(session_factory, product, previous)
    failing_ai = RecordingAIProvider(fail=True)
    failing_content_runner = make_runner(
        offers=(offer,),
        snapshot=current,
        session_factory=session_factory,
        ai_provider=failing_ai,
    )
    failed_content = await failing_content_runner.run("verify://retry-content")
    recovery_ai = RecordingAIProvider()
    recovery_runner = make_runner(
        offers=(offer,),
        snapshot=current,
        session_factory=session_factory,
        ai_provider=recovery_ai,
    )
    recovery = await recovery_runner.run("verify://retry-content")
    verification.check(
        "content failure leaves persistence committed",
        failed_content.persistence_committed and len(failed_content.errors) == 1,
    )
    verification.check(
        "retry after content failure is persistence-idempotent",
        recovery.snapshots_persisted == 0
        and await count_rows(session_factory, Offer) == 1,
    )
    verification.check(
        "content failure is not automatically republished",
        recovery.events_created == 0 and recovery_ai.calls == 0,
    )


async def verify_scheduler(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify scheduler retries a PostgreSQL-backed application runner."""
    print("\n=== SCHEDULER ===")
    await reset_runtime(engine)
    now = datetime(2026, 7, 29, 14, 0, tzinfo=UTC)
    product = CanonicalProduct(uuid4(), "Minecraft Premium", "games", ())
    previous = make_snapshot(
        price=Decimal("990.00"), collected_at=now - timedelta(minutes=1)
    )
    current = make_snapshot(price=Decimal("790.00"), collected_at=now)
    offer = make_offer(price=current.price, canonical_product_id=product.id)
    await seed_product_and_snapshot(session_factory, product, previous)
    scope_state = ScopeState()
    runner = make_runner(
        offers=(offer,),
        snapshot=current,
        session_factory=session_factory,
        scope_state=scope_state,
    )
    fail_once = FailOnceRunner(runner)
    scheduler = SchedulerService(tick_seconds=0.05)
    ggsel_job = GGSELJob(fail_once, url="verify://ggsel")
    playerok_job = PlayerokJob(AlwaysFailRunner(), url="verify://playerok")
    scheduler.register_job(ggsel_job, retry_count=1)
    scheduler.register_job(playerok_job, retry_count=1)
    scheduler.start()
    try:
        await scheduler.execute_job(ggsel_job.name)
        await scheduler.execute_job(playerok_job.name)
        await scheduler.execute_job(ggsel_job.name)
    finally:
        await scheduler.stop()

    ggsel_statistics = scheduler.get_statistics(ggsel_job.name)
    playerok_statistics = scheduler.get_statistics(playerok_job.name)
    verification.check(
        "scheduler retries failed application call",
        fail_once.calls == 3 and ggsel_statistics.retry_attempts == 1,
    )
    verification.check(
        "scheduler records successful executions",
        ggsel_statistics.total_executions == 2
        and ggsel_statistics.successful_executions == 2,
    )
    verification.check(
        "scheduler records terminal failure",
        playerok_statistics.failed_executions == 1
        and scheduler.get_status(playerok_job.name).state is JobExecutionState.FAILED,
    )
    verification.check(
        "scheduler continues after failed job",
        scheduler.get_status(ggsel_job.name).state is JobExecutionState.SUCCEEDED,
    )
    verification.check(
        "job delegates transaction ownership to runner scopes", scope_state.entries == 2
    )
    verification.check(
        "scheduled retry uses persisted history",
        await count_rows(session_factory, Offer) == 1
        and await count_rows(session_factory, PriceSnapshotRecord) == 2,
    )


async def verify_overlap(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[int, int]:
    """Run two same-process application executions and record outcomes."""
    print("\n=== SAME-PROCESS OVERLAP ===")
    await reset_runtime(engine)
    now = datetime(2026, 7, 29, 15, 0, tzinfo=UTC)
    product = CanonicalProduct(uuid4(), "Minecraft Premium", "games", ())
    previous = make_snapshot(
        price=Decimal("990.00"), collected_at=now - timedelta(minutes=1)
    )
    current = make_snapshot(price=Decimal("790.00"), collected_at=now)
    offer = make_offer(price=current.price, canonical_product_id=product.id)
    await seed_product_and_snapshot(session_factory, product, previous)
    ai_provider = RecordingAIProvider()
    runner = make_runner(
        offers=(offer,),
        snapshot=current,
        session_factory=session_factory,
        ai_provider=ai_provider,
    )
    first, second = await asyncio.gather(
        runner.run("verify://overlap-1"),
        runner.run("verify://overlap-2"),
    )
    events = first.events_created + second.events_created
    content = first.content_items_generated + second.content_items_generated
    verification.check(
        "overlap preserves one logical offer",
        await count_rows(session_factory, Offer) == 1,
    )
    verification.check(
        "overlap suppresses exact duplicate snapshot",
        await count_rows(session_factory, PriceSnapshotRecord) == 2,
    )
    verification.check(
        "overlap completes both transactions",
        first.persistence_committed and second.persistence_committed,
    )
    print(f"Observed overlapping events: {events}")
    print(f"Observed overlapping content items: {content}")
    return events, content


async def run_verification(database_url: str) -> None:
    """Run every live PostgreSQL EPIC 12 verification section."""
    verification = Verification()
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await verify_environment(verification, engine)
        await verify_offer_repository(verification, engine, session_factory)
        await verify_snapshot_repository(verification, engine, session_factory)
        await verify_foreign_key(verification, engine, session_factory)
        await verify_scope_ownership(verification, engine, session_factory)
        await verify_runner_transactions(verification, engine, session_factory)
        await verify_retries(verification, engine, session_factory)
        await verify_scheduler(verification, engine, session_factory)
        events, content = await verify_overlap(
            verification,
            engine,
            session_factory,
        )
        print("\n=== VERIFICATION COMPLETE ===")
        print(f"Checks passed: {verification.passed}")
        print(f"Overlap events/content: {events}/{content}")
    finally:
        await engine.dispose()


def main() -> None:
    """Validate the environment and run live verification."""
    database_url = os.getenv(DATABASE_URL_ENV)
    if not database_url:
        raise SystemExit(
            f"Set {DATABASE_URL_ENV} to an isolated PostgreSQL test database."
        )
    url = make_url(database_url)
    database_name = url.database or ""
    if url.get_backend_name() != "postgresql" or not database_name.startswith(
        "epic12_"
    ):
        raise SystemExit(
            f"{DATABASE_URL_ENV} must target an isolated epic12_* PostgreSQL database."
        )
    asyncio.run(run_verification(database_url))


if __name__ == "__main__":
    main()
