# ruff: noqa: E402
from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from alembic.config import Config
from sqlalchemy import text
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

from app.domain.events import BaseEvent
from app.domain.lifecycle import ScoringStatus
from app.domain.market_events import (
    MarketEventCandidate,
    PriceDropMarketEvent,
    SnapshotIdentity,
)
from app.domain.price_snapshot import PriceSnapshot
from app.domain.processing import StateTransitionOutcome
from app.insights.scoring import EventScorer
from app.repositories.postgres import (
    PostgresMarketEventRepository,
    PostgresPriceHistoryRepository,
)
from app.repositories.provider import RepositoryProvider, create_postgres_provider
from app.scheduler import (
    JobExecutionState,
    MarketEventScoringJob,
    SchedulerService,
    StaleScoringClaimRecoveryJob,
)
from app.services.event_processing import (
    EventProcessingErrorCategory,
    EventProcessingService,
)
from app.services.event_processing_errors import PermanentEventProcessingError
from app.services.market_event_scoring_adapter import (
    MarketEventScoringAdapter,
    PriceDropScoringInput,
)
from app.services.repository_scope import RepositoryScopeFactory
from tests.repositories.contracts.factories import NOW, make_event

DATABASE_URL_ENV = "EPIC13_DATABASE_URL"


class VerificationError(RuntimeError):
    """Raised when one live Task 5 assertion fails."""


class Verification:
    """Print and count focused live event-processing checks."""

    def __init__(self) -> None:
        self.passed = 0

    def check(self, label: str, condition: bool) -> None:
        """Record one passing condition or stop verification."""
        if not condition:
            raise VerificationError(label)
        self.passed += 1
        print(f"PASS: {label}")


class ScopeTracker:
    """Track open repository scopes around deterministic scoring."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self.active = 0

    def factory(self) -> RepositoryScopeFactory:
        """Create tracked PostgreSQL transaction scopes."""

        @asynccontextmanager
        async def scope() -> AsyncIterator[RepositoryProvider]:
            async with self._session_factory() as session, session.begin():
                self.active += 1
                try:
                    yield create_postgres_provider(session)
                finally:
                    self.active -= 1

        return scope


class ScopeAssertingScorer(EventScorer):
    """Assert deterministic scoring runs after the claim transaction commits."""

    def __init__(self, tracker: ScopeTracker) -> None:
        self._tracker = tracker
        self.calls = 0

    def score(self, event: BaseEvent) -> int:
        """Run the existing scorer only outside repository scopes."""
        if self._tracker.active != 0:
            raise VerificationError("scoring executed inside a repository scope")
        self.calls += 1
        return super().score(event)


class RaisingScorer(EventScorer):
    """Raise a controlled retryable scoring failure."""

    def score(self, event: BaseEvent) -> int:
        """Fail one attempt without exposing sensitive details."""
        del event
        msg = "temporary verification failure with secret-value"
        raise RuntimeError(msg)


class PermanentlyFailingAdapter(MarketEventScoringAdapter):
    """Reject a durable event as permanently malformed input."""

    def adapt(self, event: PriceDropMarketEvent) -> PriceDropScoringInput:
        """Raise the explicit permanent application error."""
        del event
        msg = "unsupported verification payload"
        raise PermanentEventProcessingError(msg)


def postgres_scope_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> RepositoryScopeFactory:
    """Create one short PostgreSQL transaction per service operation."""

    @asynccontextmanager
    async def scope() -> AsyncIterator[RepositoryProvider]:
        async with session_factory() as session, session.begin():
            yield create_postgres_provider(session)

    return scope


def make_service(
    session_factory: async_sessionmaker[AsyncSession],
    scorer: EventScorer,
    *,
    adapter: MarketEventScoringAdapter | None = None,
    scope_factory: RepositoryScopeFactory | None = None,
) -> EventProcessingService:
    """Compose the real Task 5 application service."""
    return EventProcessingService(
        repository_scope_factory=scope_factory
        or postgres_scope_factory(session_factory),
        scorer=scorer,
        adapter=adapter,
    )


async def reset_database(engine: AsyncEngine) -> None:
    """Clear event verification data in the isolated database."""
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE TABLE market_events, price_snapshots RESTART IDENTITY CASCADE"
            )
        )


async def seed_event(
    session_factory: async_sessionmaker[AsyncSession],
    number: int = 1,
) -> PriceDropMarketEvent:
    """Persist exact snapshots and one pending durable event."""
    event = make_event(number=number)
    async with session_factory() as session, session.begin():
        history = PostgresPriceHistoryRepository(session)
        await history.add(to_snapshot(event.previous_snapshot))
        await history.add(to_snapshot(event.current_snapshot))
        await PostgresMarketEventRepository(session).add_idempotently(
            MarketEventCandidate(event=event)
        )
    return event


def to_snapshot(identity: SnapshotIdentity) -> PriceSnapshot:
    """Convert an exact event snapshot identity to repository input."""
    return PriceSnapshot(
        marketplace=identity.marketplace,
        external_id=identity.external_id,
        price=identity.price,
        currency=identity.currency,
        collected_at=identity.collected_at,
    )


async def load_event(
    session_factory: async_sessionmaker[AsyncSession],
    event: PriceDropMarketEvent,
) -> PriceDropMarketEvent:
    """Reload one event through a fresh session and explicit domain mapping."""
    async with session_factory() as session:
        stored = await PostgresMarketEventRepository(session).get_by_id(event.id)
    if stored is None:
        raise VerificationError(f"event {event.id} was not persisted")
    return stored


async def verify_success(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify pending creation, claim, scoring, and duplicate exclusion."""
    await reset_database(engine)
    event = await seed_event(session_factory)
    pending = await load_event(session_factory, event)
    verification.check(
        "pending durable event created",
        pending.scoring_status is ScoringStatus.PENDING,
    )

    tracker = ScopeTracker(session_factory)
    scorer = ScopeAssertingScorer(tracker)
    service = make_service(
        session_factory,
        scorer,
        scope_factory=tracker.factory(),
    )
    result = await service.process_pending(
        worker_id="live-worker",
        limit=1,
        now=NOW + timedelta(minutes=10),
    )
    verification.check(
        "event claimed and scored once",
        result.claimed == result.scored == 1 and scorer.calls == 1,
    )
    stored = await load_event(session_factory, event)
    verification.check(
        "score and success state survive a fresh session",
        stored.scoring_status is ScoringStatus.SUCCEEDED
        and stored.score == 60
        and stored.claim is None,
    )
    repeated = await service.process_pending(
        worker_id="live-worker",
        limit=1,
        now=NOW + timedelta(minutes=11),
    )
    verification.check(
        "success prevents duplicate scoring",
        repeated.claimed == 0 and scorer.calls == 1,
    )
    verification.check(
        "no repository transaction remains open during scoring",
        tracker.active == 0,
    )


async def verify_concurrency(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify SKIP LOCKED distribution and one-event contention."""
    await reset_database(engine)
    await seed_event(session_factory, 1)
    await seed_event(session_factory, 2)
    first, second = await asyncio.gather(
        make_service(session_factory, EventScorer()).process_pending(
            worker_id="worker-one",
            limit=1,
            now=NOW + timedelta(minutes=10),
        ),
        make_service(session_factory, EventScorer()).process_pending(
            worker_id="worker-two",
            limit=1,
            now=NOW + timedelta(minutes=10),
        ),
    )
    verification.check(
        "concurrent workers score different rows",
        first.scored == second.scored == 1
        and first.items[0].event_id != second.items[0].event_id,
    )

    await reset_database(engine)
    await seed_event(session_factory)
    first, second = await asyncio.gather(
        make_service(session_factory, EventScorer()).process_pending(
            worker_id="worker-one",
            limit=1,
            now=NOW + timedelta(minutes=10),
        ),
        make_service(session_factory, EventScorer()).process_pending(
            worker_id="worker-two",
            limit=1,
            now=NOW + timedelta(minutes=10),
        ),
    )
    verification.check(
        "one-event contention has one scoring winner",
        first.scored + second.scored == 1,
    )


async def verify_retry(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify transient failure durability and successful retry."""
    await reset_database(engine)
    event = await seed_event(session_factory)
    failed_at = NOW + timedelta(minutes=10)
    failed = await make_service(session_factory, RaisingScorer()).process_pending(
        worker_id="retry-worker",
        limit=1,
        now=failed_at,
    )
    stored_failure = await load_event(session_factory, event)
    verification.check(
        "transient failure schedules durable retry",
        failed.retry_scheduled == 1
        and stored_failure.scoring_status is ScoringStatus.FAILED
        and stored_failure.next_retry_at == failed_at + timedelta(seconds=5)
        and stored_failure.last_error is not None
        and "secret-value" not in stored_failure.last_error.summary,
    )
    retried = await make_service(session_factory, EventScorer()).process_pending(
        worker_id="retry-worker",
        limit=1,
        now=failed_at + timedelta(seconds=5),
    )
    stored_success = await load_event(session_factory, event)
    verification.check(
        "retry succeeds from fresh transactions",
        retried.scored == 1
        and stored_success.scoring_status is ScoringStatus.SUCCEEDED
        and stored_success.scoring_attempt_count == 2,
    )


async def verify_recovery_job(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify active lease blocking, Scheduler recovery, and stale authority."""
    await reset_database(engine)
    event = await seed_event(session_factory)
    claimed_at = NOW + timedelta(minutes=10)
    lease_until = claimed_at + timedelta(minutes=1)
    async with session_factory() as session, session.begin():
        old_claim = (
            await PostgresMarketEventRepository(session).claim_pending(
                claimed_at,
                "crashed-worker",
                lease_until,
                1,
            )
        )[0]

    blocked = await make_service(session_factory, EventScorer()).process_pending(
        worker_id="other-worker",
        limit=1,
        now=claimed_at + timedelta(seconds=30),
    )
    verification.check("active lease blocks another worker", blocked.claimed == 0)

    service = make_service(session_factory, EventScorer())
    recovery_job = StaleScoringClaimRecoveryJob(
        service,
        batch_size=10,
        clock=lambda: lease_until,
    )
    scheduler = SchedulerService()
    scheduler.register_job(recovery_job)
    scheduler.start()
    await scheduler.execute_job(recovery_job.name)
    await scheduler.stop()
    recovered = await load_event(session_factory, event)
    verification.check(
        "Scheduler recovery job makes expired claim retryable",
        scheduler.get_status(recovery_job.name).state is JobExecutionState.SUCCEEDED
        and recovered.scoring_status is ScoringStatus.FAILED
        and recovered.next_retry_at == lease_until + timedelta(seconds=5),
    )

    async with session_factory() as session, session.begin():
        new_claim = (
            await PostgresMarketEventRepository(session).claim_pending(
                lease_until + timedelta(seconds=5),
                "new-worker",
                lease_until + timedelta(minutes=2),
                1,
            )
        )[0]
    async with session_factory() as session, session.begin():
        stale = await PostgresMarketEventRepository(session).mark_scored(
            event.id,
            old_claim.claim.token,
            new_claim.event.version,
            60,
            lease_until + timedelta(seconds=6),
        )
    verification.check(
        "stale claim token cannot complete reclaimed event",
        stale.outcome is StateTransitionOutcome.CLAIM_LOST,
    )


async def verify_permanent_failure(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify malformed input reaches explicit terminal failed state."""
    await reset_database(engine)
    event = await seed_event(session_factory)
    service = make_service(
        session_factory,
        EventScorer(),
        adapter=PermanentlyFailingAdapter(),
    )
    result = await service.process_pending(
        worker_id="permanent-worker",
        limit=1,
        now=NOW + timedelta(minutes=10),
    )
    stored = await load_event(session_factory, event)
    verification.check(
        "permanent input failure is terminal",
        result.permanently_failed == 1
        and stored.scoring_status is ScoringStatus.FAILED
        and stored.next_retry_at is None
        and stored.last_error is not None
        and stored.last_error.code
        == EventProcessingErrorCategory.PERMANENT_INPUT.value,
    )


async def verify_scoring_job(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify Scheduler scoring job delegates to the real application service."""
    await reset_database(engine)
    event = await seed_event(session_factory)
    service = make_service(session_factory, EventScorer())
    scoring_job = MarketEventScoringJob(
        service,
        worker_id="scheduler-worker",
        batch_size=10,
        clock=lambda: NOW + timedelta(minutes=10),
    )
    scheduler = SchedulerService()
    scheduler.register_job(scoring_job)
    scheduler.start()
    await scheduler.execute_job(scoring_job.name)
    await scheduler.stop()
    stored = await load_event(session_factory, event)
    verification.check(
        "Scheduler scoring job persists success",
        scheduler.get_status(scoring_job.name).state is JobExecutionState.SUCCEEDED
        and scheduler.get_statistics(scoring_job.name).successful_executions == 1
        and stored.scoring_status is ScoringStatus.SUCCEEDED,
    )


async def run_verification(database_url: str) -> None:
    """Run focused live Task 5 verification."""
    verification = Verification()
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await verify_success(verification, engine, session_factory)
        await verify_concurrency(verification, engine, session_factory)
        await verify_retry(verification, engine, session_factory)
        await verify_recovery_job(verification, engine, session_factory)
        await verify_permanent_failure(verification, engine, session_factory)
        await verify_scoring_job(verification, engine, session_factory)
        await reset_database(engine)
        print(f"Checks passed: {verification.passed}")
        print("SUCCESS")
    finally:
        await engine.dispose()


def apply_migrations(database_url: str) -> None:
    """Apply project migrations to the isolated verification database."""
    os.environ["DATABASE_URL"] = database_url
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")


def main() -> None:
    """Guard the database, apply migrations, and run live verification."""
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
