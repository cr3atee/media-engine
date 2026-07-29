from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database.metadata import get_metadata
from app.domain.events import BaseEvent
from app.domain.lifecycle import ScoringStatus
from app.domain.market_events import (
    MarketEventCandidate,
    PriceDropMarketEvent,
    SnapshotIdentity,
)
from app.domain.price_snapshot import PriceSnapshot
from app.domain.processing import StateTransitionResult
from app.insights.scoring import EventScorer
from app.models.market_event_record import MarketEventRecord
from app.models.price_snapshot_record import PriceSnapshotRecord
from app.repositories.postgres import (
    PostgresMarketEventRepository,
    PostgresPriceHistoryRepository,
)
from app.repositories.provider import RepositoryProvider, create_postgres_provider
from app.services.event_processing import (
    EventProcessingErrorCategory,
    EventProcessingService,
    ScoringRetryPolicy,
)
from app.services.event_processing_errors import PermanentEventProcessingError
from app.services.market_event_scoring_adapter import (
    MarketEventScoringAdapter,
    PriceDropScoringInput,
)
from app.services.repository_scope import RepositoryScopeFactory
from tests.repositories.contracts.factories import NOW, make_event, run_async

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


class RaisingScorer(EventScorer):
    """Raise a controlled transient scoring failure."""

    def score(self, event: BaseEvent) -> int:
        """Fail without changing the scoring algorithm implementation."""
        del event
        msg = "temporary scorer failure"
        raise RuntimeError(msg)


class PermanentlyFailingAdapter(MarketEventScoringAdapter):
    """Represent an unsupported durable event input."""

    def adapt(self, event: PriceDropMarketEvent) -> PriceDropScoringInput:
        """Reject one claimed event as permanent input failure."""
        del event
        msg = "unsupported durable event"
        raise PermanentEventProcessingError(msg)


class MarkThenFailRepository(PostgresMarketEventRepository):
    """Flush a score update and fail before transaction commit."""

    async def mark_scored(
        self,
        event_id: UUID,
        claim_token: UUID,
        expected_version: int,
        score: int,
        completed_at: datetime,
    ) -> StateTransitionResult:
        """Delegate the guarded update, then trigger outer rollback."""
        await super().mark_scored(
            event_id,
            claim_token,
            expected_version,
            score,
            completed_at,
        )
        msg = "controlled score completion rollback"
        raise RuntimeError(msg)


def test_claim_commit_score_completion_and_fresh_session_visibility() -> None:
    async def scenario() -> None:
        await reset_database()
        event = await seed_event()
        service = make_service(EventScorer())

        result = await service.process_pending(
            worker_id="worker-one",
            limit=10,
            now=NOW + timedelta(minutes=10),
        )
        stored = await load_event(event.id)
        repeated = await make_service(EventScorer()).process_pending(
            worker_id="worker-two",
            limit=10,
            now=NOW + timedelta(minutes=11),
        )

        assert result.claimed == 1
        assert result.scored == 1
        assert stored is not None
        assert stored.scoring_status is ScoringStatus.SUCCEEDED
        assert stored.score == 60
        assert stored.claim is None
        assert stored.scoring_attempt_count == 1
        assert repeated.claimed == 0

    run_async(scenario())


def test_concurrent_workers_split_rows_and_one_event_has_one_winner() -> None:
    async def process_two() -> None:
        await reset_database()
        await seed_event(1)
        await seed_event(2)
        first, second = await asyncio.gather(
            make_service(EventScorer()).process_pending(
                worker_id="worker-one",
                limit=1,
                now=NOW + timedelta(minutes=10),
            ),
            make_service(EventScorer()).process_pending(
                worker_id="worker-two",
                limit=1,
                now=NOW + timedelta(minutes=10),
            ),
        )

        assert first.claimed == second.claimed == 1
        assert first.items[0].event_id != second.items[0].event_id
        assert await scored_count() == 2

        await reset_database()
        await seed_event(1)
        first, second = await asyncio.gather(
            make_service(EventScorer()).process_pending(
                worker_id="worker-one",
                limit=1,
                now=NOW + timedelta(minutes=10),
            ),
            make_service(EventScorer()).process_pending(
                worker_id="worker-two",
                limit=1,
                now=NOW + timedelta(minutes=10),
            ),
        )

        assert first.claimed + second.claimed == 1
        assert await scored_count() == 1

    run_async(process_two())


def test_transient_retry_survives_fresh_service_and_session() -> None:
    async def scenario() -> None:
        await reset_database()
        event = await seed_event()
        failed_at = NOW + timedelta(minutes=10)
        failed = await make_service(RaisingScorer()).process_pending(
            worker_id="worker-one",
            limit=1,
            now=failed_at,
        )
        stored_failure = await load_event(event.id)

        retried = await make_service(EventScorer()).process_pending(
            worker_id="worker-two",
            limit=1,
            now=failed_at + timedelta(seconds=5),
        )
        stored_success = await load_event(event.id)

        assert failed.retry_scheduled == 1
        assert stored_failure is not None
        assert stored_failure.scoring_status is ScoringStatus.FAILED
        assert stored_failure.next_retry_at == failed_at + timedelta(seconds=5)
        assert retried.scored == 1
        assert stored_success is not None
        assert stored_success.scoring_status is ScoringStatus.SUCCEEDED
        assert stored_success.scoring_attempt_count == 2

    run_async(scenario())


def test_completion_rollback_leaves_claim_for_expiry_recovery() -> None:
    async def scenario() -> None:
        await reset_database()
        event = await seed_event()
        claimed_at = NOW + timedelta(minutes=10)
        service = EventProcessingService(
            repository_scope_factory=failing_completion_scope_factory(),
            scorer=EventScorer(),
        )

        result = await service.process_pending(
            worker_id="worker",
            limit=1,
            now=claimed_at,
        )
        still_claimed = await load_event(event.id)
        recovery = await make_service(EventScorer()).recover_stale_scoring_claims(
            limit=1,
            now=claimed_at + timedelta(minutes=1),
        )
        recovered = await load_event(event.id)

        assert (
            result.items[0].error_category is EventProcessingErrorCategory.PERSISTENCE
        )
        assert still_claimed is not None
        assert still_claimed.scoring_status is ScoringStatus.IN_PROGRESS
        assert still_claimed.score is None
        assert recovery.recovered == 1
        assert recovered is not None
        assert recovered.scoring_status is ScoringStatus.FAILED
        assert recovered.next_retry_at is not None

    run_async(scenario())


def test_permanent_failure_is_terminal_and_persisted() -> None:
    async def scenario() -> None:
        await reset_database()
        event = await seed_event()
        service = EventProcessingService(
            repository_scope_factory=postgres_scope_factory(),
            scorer=EventScorer(),
            adapter=PermanentlyFailingAdapter(),
            retry_policy=ScoringRetryPolicy(maximum_attempts=3),
        )

        result = await service.process_pending(
            worker_id="worker",
            limit=1,
            now=NOW + timedelta(minutes=10),
        )
        stored = await load_event(event.id)

        assert result.permanently_failed == 1
        assert stored is not None
        assert stored.scoring_status is ScoringStatus.FAILED
        assert stored.next_retry_at is None
        assert stored.last_error is not None
        assert stored.last_error.code == "permanent_input"

    run_async(scenario())


def make_service(scorer: EventScorer) -> EventProcessingService:
    """Create an event-processing service backed by fresh PostgreSQL scopes."""
    return EventProcessingService(
        repository_scope_factory=postgres_scope_factory(),
        scorer=scorer,
    )


def postgres_scope_factory() -> RepositoryScopeFactory:
    """Create one caller-owned transaction per application scope."""

    @asynccontextmanager
    async def scope() -> AsyncIterator[RepositoryProvider]:
        async with session_factory()() as session, session.begin():
            yield create_postgres_provider(session)

    return scope


def failing_completion_scope_factory() -> RepositoryScopeFactory:
    """Create scopes whose score completion rolls back after flush."""

    @asynccontextmanager
    async def scope() -> AsyncIterator[RepositoryProvider]:
        async with session_factory()() as session, session.begin():
            provider = create_postgres_provider(session)
            provider.events = MarkThenFailRepository(session)
            yield provider

    return scope


async def seed_event(number: int = 1) -> PriceDropMarketEvent:
    """Persist exact snapshots and one pending event."""
    event = make_event(number=number)
    async with session_factory()() as session, session.begin():
        history = PostgresPriceHistoryRepository(session)
        await history.add(to_snapshot(event.previous_snapshot))
        await history.add(to_snapshot(event.current_snapshot))
        await PostgresMarketEventRepository(session).add_idempotently(
            MarketEventCandidate(event=event)
        )
    return event


async def load_event(event_id: UUID) -> PriceDropMarketEvent | None:
    """Load one event through a fresh PostgreSQL session."""
    async with session_factory()() as session:
        return await PostgresMarketEventRepository(session).get_by_id(event_id)


async def scored_count() -> int:
    """Count successfully scored event rows."""
    async with session_factory()() as session:
        result = await session.execute(
            select(func.count())
            .select_from(MarketEventRecord)
            .where(MarketEventRecord.scoring_status == ScoringStatus.SUCCEEDED.value)
        )
        return int(result.scalar_one())


async def reset_database() -> None:
    """Create metadata and clear event dependencies in the isolated database."""
    async with engine().begin() as connection:
        await connection.run_sync(get_metadata().create_all)
        await connection.execute(delete(MarketEventRecord))
        await connection.execute(delete(PriceSnapshotRecord))


def to_snapshot(identity: SnapshotIdentity) -> PriceSnapshot:
    """Convert one durable snapshot identity to the repository input."""
    return PriceSnapshot(
        marketplace=identity.marketplace,
        external_id=identity.external_id,
        price=identity.price,
        currency=identity.currency,
        collected_at=identity.collected_at,
    )


def engine() -> AsyncEngine:
    """Return the guarded live test engine."""
    if _ENGINE is None:
        raise RuntimeError(_SKIP_REASON)
    return _ENGINE


def session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the guarded live test session factory."""
    if _SESSION_FACTORY is None:
        raise RuntimeError(_SKIP_REASON)
    return _SESSION_FACTORY


def teardown_module() -> None:
    """Dispose the optional PostgreSQL test engine."""
    if _ENGINE is not None:
        run_async(_ENGINE.dispose())
