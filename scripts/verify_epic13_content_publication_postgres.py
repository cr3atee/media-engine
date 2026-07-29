# ruff: noqa: E402
from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from uuid import UUID

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

from app.ai.provider import AIProvider
from app.domain.generated_content import (
    CreateContentAttempt,
    GeneratedContentAttempt,
    calculate_content_checksum,
)
from app.domain.lifecycle import ContentGenerationStatus, PublicationStatus
from app.domain.market_events import (
    MarketEventCandidate,
    PriceDropMarketEvent,
    SnapshotIdentity,
)
from app.domain.price_snapshot import PriceSnapshot
from app.domain.publications import CreatePublication, Publication
from app.repositories.provider import RepositoryProvider, create_postgres_provider
from app.scheduler import (
    JobExecutionState,
    PendingContentGenerationJob,
    SchedulerService,
    StaleContentClaimRecoveryJob,
    StalePublicationClaimRecoveryJob,
)
from app.services.content_generator import ContentGenerator
from app.services.content_processing import (
    ContentGenerationDescriptor,
    ContentGenerationProcessingService,
    ContentProcessingErrorCategory,
    ContentRetryPolicy,
)
from app.services.publication_intents import (
    PublicationIntentService,
    PublicationTarget,
)
from app.services.repository_scope import RepositoryScopeFactory
from tests.repositories.contracts.factories import NOW, make_event, uuid_for

DATABASE_URL_ENV = "EPIC13_DATABASE_URL"


class VerificationError(RuntimeError):
    """Raised when one live content/publication assertion fails."""


class Verification:
    """Print and count focused live Task 6 checks."""

    def __init__(self) -> None:
        self.passed = 0

    def check(self, label: str, condition: bool) -> None:
        """Record one passing condition or stop verification."""
        if not condition:
            raise VerificationError(label)
        self.passed += 1
        print(f"PASS: {label}")


class TrackedScopes:
    """Create short PostgreSQL scopes and expose active transaction state."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        fail_on_exit_entry: int | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._fail_on_exit_entry = fail_on_exit_entry
        self.active = 0
        self.entries = 0

    def factory(self) -> RepositoryScopeFactory:
        """Return a transaction scope factory for application services."""
        return self.scope

    @asynccontextmanager
    async def scope(self) -> AsyncIterator[RepositoryProvider]:
        self.entries += 1
        entry = self.entries
        async with self._session_factory() as session, session.begin():
            self.active += 1
            try:
                yield create_postgres_provider(session)
                if entry == self._fail_on_exit_entry:
                    msg = "simulated completion transaction failure"
                    raise RuntimeError(msg)
            finally:
                self.active -= 1


class DeterministicProvider(AIProvider):
    """Return controlled responses and observe transaction boundaries."""

    def __init__(
        self,
        scopes: TrackedScopes,
        responses: list[str | Exception],
        *,
        on_call: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._scopes = scopes
        self._responses = responses
        self._on_call = on_call
        self.calls = 0
        self.scope_states: list[int] = []

    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        """Return one deterministic response without external I/O."""
        del system_prompt, user_prompt
        self.scope_states.append(self._scopes.active)
        if self._on_call is not None:
            await self._on_call()
        response = self._responses[self.calls]
        self.calls += 1
        if isinstance(response, Exception):
            raise response
        return response


def make_scope_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> RepositoryScopeFactory:
    """Create ordinary short PostgreSQL transaction scopes."""

    @asynccontextmanager
    async def scope() -> AsyncIterator[RepositoryProvider]:
        async with session_factory() as session, session.begin():
            yield create_postgres_provider(session)

    return scope


def make_content_service(
    scopes: TrackedScopes,
    provider: AIProvider,
) -> ContentGenerationProcessingService:
    """Compose the real durable content application service."""
    publication_service = PublicationIntentService(
        repository_scope_factory=scopes.factory()
    )
    return ContentGenerationProcessingService(
        repository_scope_factory=scopes.factory(),
        content_generator=ContentGenerator(provider),
        publication_intent_service=publication_service,
        descriptor=ContentGenerationDescriptor(
            provider="fake",
            model="deterministic",
        ),
        retry_policy=ContentRetryPolicy(
            maximum_attempts=3,
            initial_delay=timedelta(seconds=5),
            maximum_delay=timedelta(minutes=5),
        ),
        publication_target=PublicationTarget("preview", "live-verification"),
    )


async def recreate_schema(database_url: str) -> None:
    """Recreate public schema in the explicitly isolated database."""
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


async def reset_data(engine: AsyncEngine) -> None:
    """Clear durable Task 6 data while retaining migrated schema."""
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE TABLE publications, generated_contents, market_events, "
                "price_snapshots RESTART IDENTITY CASCADE"
            )
        )


async def seed_scored_event(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    number: int = 1,
) -> PriceDropMarketEvent:
    """Persist snapshots and one successfully scored durable event."""
    event = make_event(number=number)
    async with session_factory() as session, session.begin():
        repositories = create_postgres_provider(session)
        await repositories.price_history.add(to_snapshot(event.previous_snapshot))
        await repositories.price_history.add(to_snapshot(event.current_snapshot))
        await repositories.events.add_idempotently(MarketEventCandidate(event=event))
        claimed = (
            await repositories.events.claim_pending(
                NOW + timedelta(minutes=10),
                "score-worker",
                NOW + timedelta(minutes=11),
                1,
            )
        )[0]
        await repositories.events.mark_scored(
            event.id,
            claimed.claim.token,
            claimed.event.version,
            80,
            NOW + timedelta(minutes=10, seconds=1),
        )
    return event


def to_snapshot(identity: SnapshotIdentity) -> PriceSnapshot:
    """Convert durable event snapshot identity to repository input."""
    return PriceSnapshot(
        marketplace=identity.marketplace,
        external_id=identity.external_id,
        price=identity.price,
        currency=identity.currency,
        collected_at=identity.collected_at,
    )


async def load_work(
    session_factory: async_sessionmaker[AsyncSession],
    event_id: UUID,
) -> tuple[tuple[GeneratedContentAttempt, ...], tuple[Publication, ...]]:
    """Load event content and publications through a fresh session."""
    async with session_factory() as session:
        repositories = create_postgres_provider(session)
        return (
            tuple(await repositories.generated_contents.list_for_event(event_id)),
            tuple(await repositories.publications.list_for_event(event_id)),
        )


async def verify_success_and_idempotency(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify eligibility, durable claims, success, and idempotency."""
    await reset_data(engine)
    event = await seed_scored_event(session_factory)
    async with session_factory() as session:
        eligible = await create_postgres_provider(session).events.list_content_eligible(
            10
        )
    verification.check(
        "scored event becomes content eligible",
        len(eligible) == 1 and eligible[0].id == event.id,
    )

    claim_visible = False

    async def inspect_claim() -> None:
        nonlocal claim_visible
        contents, _ = await load_work(session_factory, event.id)
        claim_visible = (
            len(contents) == 1
            and contents[0].generation_status is ContentGenerationStatus.IN_PROGRESS
            and contents[0].claim is not None
        )

    scopes = TrackedScopes(session_factory)
    ai = DeterministicProvider(
        scopes,
        ["Durable generated content"],
        on_call=inspect_claim,
    )
    service = make_content_service(scopes, ai)
    result = await service.process_pending(
        worker_id="content-worker",
        limit=1,
        now=NOW + timedelta(minutes=20),
    )
    verification.check("generation claim survives its commit", claim_visible)
    verification.check(
        "AI executes outside database transactions",
        ai.scope_states == [0] and scopes.active == 0,
    )
    verification.check(
        "AI success creates durable content",
        result.generated == 1,
    )
    verification.check(
        "successful content creates a publication intent",
        result.publications_created == 1,
    )
    contents, publications = await load_work(session_factory, event.id)
    verification.check(
        "publication intent is durable in a fresh session",
        len(contents) == len(publications) == 1
        and contents[0].content_text == "Durable generated content"
        and publications[0].status is PublicationStatus.PENDING,
    )

    repeated = await service.process_pending(
        worker_id="content-worker",
        limit=1,
        now=NOW + timedelta(minutes=21),
    )
    duplicate_contents, duplicate_publications = await load_work(
        session_factory, event.id
    )
    verification.check(
        "duplicate processing creates no duplicate attempt or publication",
        repeated.claimed == 0
        and ai.calls == 1
        and len(duplicate_contents) == len(duplicate_publications) == 1,
    )

    scope_factory = make_scope_factory(session_factory)
    intent_service = PublicationIntentService(repository_scope_factory=scope_factory)
    async with scope_factory() as repositories:
        duplicate = await intent_service.create(
            repositories.publications,
            event_id=event.id,
            content_id=contents[0].id,
            target=PublicationTarget("preview", "live-verification"),
            created_at=NOW + timedelta(minutes=22),
        )
    verification.check(
        "publication idempotency keeps one logical delivery intent",
        not duplicate.created,
    )


async def verify_retry(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify durable transient failure and a fresh-service retry."""
    await reset_data(engine)
    event = await seed_scored_event(session_factory)
    failed_scopes = TrackedScopes(session_factory)
    failed = await make_content_service(
        failed_scopes,
        DeterministicProvider(failed_scopes, [RuntimeError("temporary secret")]),
    ).process_pending(
        worker_id="failed-worker",
        limit=1,
        now=NOW + timedelta(minutes=20),
    )
    failed_contents, failed_publications = await load_work(session_factory, event.id)
    verification.check(
        "AI failure persists sanitized retry state",
        failed.retry_scheduled == 1
        and failed.items[0].error_category is ContentProcessingErrorCategory.TRANSIENT
        and len(failed_contents) == 1
        and failed_contents[0].next_retry_at == NOW + timedelta(minutes=20, seconds=5),
    )
    verification.check(
        "failed generation creates no publication",
        failed_publications == (),
    )

    retry_scopes = TrackedScopes(session_factory)
    retried = await make_content_service(
        retry_scopes,
        DeterministicProvider(retry_scopes, ["Recovered content"]),
    ).process_pending(
        worker_id="retry-worker",
        limit=1,
        now=NOW + timedelta(minutes=20, seconds=5),
    )
    contents, publications = await load_work(session_factory, event.id)
    verification.check(
        "retry creates a new immutable attempt and succeeds",
        retried.generated == 1
        and tuple(item.attempt_number for item in contents) == (1, 2)
        and len(publications) == 1,
    )


async def verify_concurrency(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify two workers cannot generate one logical attempt twice."""
    await reset_data(engine)
    event = await seed_scored_event(session_factory)
    first_scopes = TrackedScopes(session_factory)
    second_scopes = TrackedScopes(session_factory)
    first_ai = DeterministicProvider(first_scopes, ["First worker"])
    second_ai = DeterministicProvider(second_scopes, ["Second worker"])
    first, second = await asyncio.gather(
        make_content_service(first_scopes, first_ai).process_pending(
            worker_id="worker-one",
            limit=1,
            now=NOW + timedelta(minutes=20),
        ),
        make_content_service(second_scopes, second_ai).process_pending(
            worker_id="worker-two",
            limit=1,
            now=NOW + timedelta(minutes=20),
        ),
    )
    contents, publications = await load_work(session_factory, event.id)
    verification.check(
        "concurrent workers have one generation winner",
        first.generated + second.generated == 1
        and first_ai.calls + second_ai.calls == 1
        and len(contents) == len(publications) == 1,
    )


async def verify_completion_rollback(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify content completion and publication creation are atomic."""
    await reset_data(engine)
    event = await seed_scored_event(session_factory)
    scopes = TrackedScopes(session_factory, fail_on_exit_entry=2)
    result = await make_content_service(
        scopes,
        DeterministicProvider(scopes, ["Rolled back content"]),
    ).process_pending(
        worker_id="rollback-worker",
        limit=1,
        now=NOW + timedelta(minutes=20),
    )
    contents, publications = await load_work(session_factory, event.id)
    verification.check(
        "completion rollback leaves no partial content or publication",
        result.items[0].error_category is ContentProcessingErrorCategory.PERSISTENCE
        and contents[0].generation_status is ContentGenerationStatus.IN_PROGRESS
        and contents[0].content_text is None
        and publications == (),
    )


async def seed_expired_claims(
    session_factory: async_sessionmaker[AsyncSession],
    event: PriceDropMarketEvent,
) -> tuple[UUID, UUID]:
    """Create independent expired generation and publication claims."""
    async with session_factory() as session, session.begin():
        repositories = create_postgres_provider(session)
        stale_content = CreateContentAttempt(
            id=uuid_for(60_001),
            event_id=event.id,
            content_type="stale_content",
            language="ru",
            prompt_version="price_drop_v1",
            attempt_number=1,
            provider="fake",
            model="deterministic",
            created_at=NOW + timedelta(minutes=20),
        )
        await repositories.generated_contents.create_attempt(stale_content)
        await repositories.generated_contents.claim_pending(
            NOW + timedelta(minutes=20),
            "crashed-content-worker",
            NOW + timedelta(minutes=21),
            1,
        )

        source = CreateContentAttempt(
            id=uuid_for(60_002),
            event_id=event.id,
            content_type="publication_source",
            language="ru",
            prompt_version="price_drop_v1",
            attempt_number=1,
            provider="fake",
            model="deterministic",
            created_at=NOW + timedelta(minutes=20, seconds=1),
        )
        await repositories.generated_contents.create_attempt(source)
        claimed = (
            await repositories.generated_contents.claim_pending(
                NOW + timedelta(minutes=20, seconds=1),
                "publication-source-worker",
                NOW + timedelta(minutes=21, seconds=1),
                1,
            )
        )[0]
        content_text = "Publication recovery source"
        await repositories.generated_contents.complete_attempt(
            source.id,
            claimed.claim.token,
            claimed.content.version,
            content_text,
            calculate_content_checksum(content_text),
            NOW + timedelta(minutes=20, seconds=2),
        )
        publication = CreatePublication(
            id=uuid_for(60_003),
            event_id=event.id,
            content_id=source.id,
            channel="preview",
            destination_key="stale-publication",
            created_at=NOW + timedelta(minutes=20, seconds=3),
        )
        await repositories.publications.create_idempotently(publication)
        await repositories.publications.claim_pending(
            NOW + timedelta(minutes=20, seconds=4),
            "crashed-publication-worker",
            NOW + timedelta(minutes=21),
            1,
        )
    return stale_content.id, publication.id


async def verify_recovery_jobs(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify Scheduler delegates safe stale-claim recovery."""
    await reset_data(engine)
    event = await seed_scored_event(session_factory)
    stale_content_id, stale_publication_id = await seed_expired_claims(
        session_factory, event
    )
    scopes = TrackedScopes(session_factory)
    content_service = make_content_service(
        scopes,
        DeterministicProvider(scopes, []),
    )
    publication_service = PublicationIntentService(
        repository_scope_factory=scopes.factory()
    )
    content_job = StaleContentClaimRecoveryJob(
        content_service,
        batch_size=10,
        clock=lambda: NOW + timedelta(minutes=21),
    )
    publication_job = StalePublicationClaimRecoveryJob(
        publication_service,
        batch_size=10,
        clock=lambda: NOW + timedelta(minutes=21),
    )
    scheduler = SchedulerService()
    scheduler.register_job(content_job)
    scheduler.register_job(publication_job)
    scheduler.start()
    await scheduler.execute_job(content_job.name)
    await scheduler.execute_job(publication_job.name)
    await scheduler.stop()

    async with session_factory() as session:
        repositories = create_postgres_provider(session)
        stale_content = await repositories.generated_contents.get_by_id(
            stale_content_id
        )
        stale_publication = await repositories.publications.get_by_id(
            stale_publication_id
        )
        retry_claim = await repositories.publications.claim_pending(
            NOW + timedelta(minutes=22),
            "unsafe-retry-worker",
            NOW + timedelta(minutes=23),
            10,
        )
    verification.check(
        "stale content recovery job abandons the expired claim",
        scheduler.get_status(content_job.name).state is JobExecutionState.SUCCEEDED
        and stale_content is not None
        and stale_content.generation_status is ContentGenerationStatus.ABANDONED,
    )
    verification.check(
        "stale publication recovery job records an ambiguous outcome",
        scheduler.get_status(publication_job.name).state is JobExecutionState.SUCCEEDED
        and stale_publication is not None
        and stale_publication.status is PublicationStatus.AMBIGUOUS,
    )
    verification.check(
        "ambiguous publication is not automatically retried",
        retry_claim == (),
    )


async def verify_generation_job(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify Scheduler content job delegates to the application service."""
    await reset_data(engine)
    event = await seed_scored_event(session_factory)
    scopes = TrackedScopes(session_factory)
    ai = DeterministicProvider(scopes, ["Scheduler generated content"])
    service = make_content_service(scopes, ai)
    job = PendingContentGenerationJob(
        service,
        worker_id="scheduler-content-worker",
        batch_size=10,
        clock=lambda: NOW + timedelta(minutes=20),
    )
    scheduler = SchedulerService()
    scheduler.register_job(job)
    scheduler.start()
    await scheduler.execute_job(job.name)
    await scheduler.stop()
    contents, publications = await load_work(session_factory, event.id)
    verification.check(
        "Scheduler generation job persists content and publication intent",
        scheduler.get_status(job.name).state is JobExecutionState.SUCCEEDED
        and len(contents) == len(publications) == 1
        and ai.calls == 1,
    )


async def verify_migration(
    verification: Verification,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify Alembic reached the focused Task 6 revision."""
    async with session_factory() as session:
        revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
    verification.check(
        "migrations apply through Task 6", revision == "0008_content_publications"
    )


async def run_verification(database_url: str) -> None:
    """Run all live Task 6 checks against isolated PostgreSQL."""
    verification = Verification()
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await verify_migration(verification, session_factory)
        await verify_success_and_idempotency(verification, engine, session_factory)
        await verify_retry(verification, engine, session_factory)
        await verify_concurrency(verification, engine, session_factory)
        await verify_completion_rollback(verification, engine, session_factory)
        await verify_recovery_jobs(verification, engine, session_factory)
        await verify_generation_job(verification, engine, session_factory)
        await reset_data(engine)
        print(f"Checks passed: {verification.passed}")
        print("SUCCESS")
    finally:
        await engine.dispose()


def apply_migrations(database_url: str) -> None:
    """Apply project migrations to the isolated verification database."""
    os.environ["DATABASE_URL"] = database_url
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")


def main() -> None:
    """Guard the database, migrate it, and run live verification."""
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
    asyncio.run(recreate_schema(database_url))
    apply_migrations(database_url)
    asyncio.run(run_verification(database_url))


if __name__ == "__main__":
    main()
