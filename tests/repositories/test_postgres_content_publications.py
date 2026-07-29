from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database.metadata import get_metadata
from app.domain.generated_content import CreateContentAttempt
from app.domain.market_events import MarketEventCandidate
from app.domain.price_snapshot import PriceSnapshot
from app.domain.publications import CreatePublication
from app.repositories.postgres import (
    PostgresGeneratedContentRepository,
    PostgresMarketEventRepository,
    PostgresPriceHistoryRepository,
    PostgresPublicationRepository,
)
from tests.repositories.contracts.factories import (
    NOW,
    SequentialUuidFactory,
    make_event,
    run_async,
    uuid_for,
)
from tests.repositories.contracts.persistent import (
    GeneratedContentRepositoryContract,
    PublicationRepositoryContract,
)

DATABASE_URL = os.getenv("EPIC13_DATABASE_URL")
_ISOLATED_DATABASE = DATABASE_URL is not None and (
    make_url(DATABASE_URL).database or ""
).startswith("epic13_")
_SKIP_REASON = (
    "EPIC13_DATABASE_URL must target an isolated epic13_* PostgreSQL database"
)
_ENGINE: AsyncEngine | None = (
    create_async_engine(DATABASE_URL)
    if DATABASE_URL is not None and _ISOLATED_DATABASE
    else None
)
_SESSION_FACTORY: async_sessionmaker[AsyncSession] | None = (
    async_sessionmaker(_ENGINE, expire_on_commit=False) if _ENGINE is not None else None
)

pytestmark = pytest.mark.skipif(not _ISOLATED_DATABASE, reason=_SKIP_REASON)


class TestPostgresGeneratedContentRepository(GeneratedContentRepositoryContract):
    """Run the shared generated-content contract against PostgreSQL."""

    _session: AsyncSession

    def setup_method(self) -> None:
        run_async(_reset_database())
        self._session = _session_factory()()
        run_async(_seed_events(self._session))

    def teardown_method(self) -> None:
        run_async(self._session.rollback())
        run_async(self._session.close())

    def make_repository(self) -> PostgresGeneratedContentRepository:
        return PostgresGeneratedContentRepository(
            self._session,
            claim_token_factory=SequentialUuidFactory(80_000),
        )


class TestPostgresPublicationRepository(PublicationRepositoryContract):
    """Run the shared publication contract against PostgreSQL."""

    _session: AsyncSession

    def setup_method(self) -> None:
        run_async(_reset_database())
        self._session = _session_factory()()
        run_async(_seed_events(self._session))
        run_async(_seed_publication_contents(self._session))

    def teardown_method(self) -> None:
        run_async(self._session.rollback())
        run_async(self._session.close())

    def make_repository(self) -> PostgresPublicationRepository:
        return PostgresPublicationRepository(
            self._session,
            claim_token_factory=SequentialUuidFactory(90_000),
        )


def test_two_postgres_workers_claim_one_publication_once() -> None:
    run_async(_reset_database())
    run_async(_seed_claimable_publication())

    async def claim(worker_id: str, token_start: int) -> int:
        async with _session_factory()() as session, session.begin():
            repository = PostgresPublicationRepository(
                session,
                claim_token_factory=SequentialUuidFactory(token_start),
            )
            claimed = await repository.claim_pending(
                NOW,
                worker_id,
                NOW.replace(minute=NOW.minute + 1),
                1,
            )
            return len(claimed)

    async def claim_concurrently() -> tuple[int, int]:
        first, second = await asyncio.gather(
            claim("publication-worker-one", 91_000),
            claim("publication-worker-two", 92_000),
        )
        return first, second

    claimed_counts = run_async(claim_concurrently())

    assert sum(claimed_counts) == 1


async def _reset_database() -> None:
    engine = _engine()
    async with engine.begin() as connection:
        await connection.run_sync(get_metadata().drop_all)
        await connection.run_sync(get_metadata().create_all)


async def _seed_events(session: AsyncSession) -> None:
    history = PostgresPriceHistoryRepository(session)
    events = PostgresMarketEventRepository(session)
    for event in (
        make_event(number=1, event_id=uuid_for(101)),
        make_event(number=2, event_id=uuid_for(102)),
    ):
        await history.add(_snapshot(event.previous_snapshot))
        await history.add(_snapshot(event.current_snapshot))
        await events.add_idempotently(MarketEventCandidate(event=event))
    await session.flush()


async def _seed_publication_contents(session: AsyncSession) -> None:
    repository = PostgresGeneratedContentRepository(session)
    event_ids = {
        uuid_for(201): uuid_for(101),
        uuid_for(202): uuid_for(101),
        uuid_for(203): uuid_for(102),
        uuid_for(211): uuid_for(101),
        uuid_for(212): uuid_for(101),
        uuid_for(213): uuid_for(101),
    }
    for index, (content_id, event_id) in enumerate(event_ids.items(), start=1):
        await repository.create_attempt(
            CreateContentAttempt(
                id=content_id,
                event_id=event_id,
                content_type=f"seed-{content_id.int}",
                language="ru",
                prompt_version="seed-v1",
                attempt_number=1,
                provider="test",
                model="deterministic",
                created_at=NOW.replace(microsecond=index),
            )
        )
    await session.flush()


async def _seed_claimable_publication() -> None:
    async with _session_factory()() as session, session.begin():
        await _seed_events(session)
        await _seed_publication_contents(session)
        repository = PostgresPublicationRepository(session)
        await repository.create_idempotently(
            CreatePublication(
                id=uuid_for(93_000),
                event_id=uuid_for(101),
                content_id=uuid_for(201),
                channel="preview",
                destination_key="concurrent-claim",
                created_at=NOW,
            )
        )


def _snapshot(snapshot: object) -> PriceSnapshot:
    from app.domain.market_events import SnapshotIdentity

    assert isinstance(snapshot, SnapshotIdentity)
    return PriceSnapshot(
        marketplace=snapshot.marketplace,
        external_id=snapshot.external_id,
        price=snapshot.price,
        currency=snapshot.currency,
        collected_at=snapshot.collected_at,
    )


def _engine() -> AsyncEngine:
    assert _ENGINE is not None
    return _ENGINE


def _session_factory() -> async_sessionmaker[AsyncSession]:
    assert _SESSION_FACTORY is not None
    return _SESSION_FACTORY
