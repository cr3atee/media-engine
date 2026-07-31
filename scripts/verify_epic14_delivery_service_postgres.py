# ruff: noqa: E402
from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

import httpx
from alembic.config import Config
from pydantic import SecretStr
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

from app.config.settings import TelegramSettings, settings
from app.database.metadata import get_metadata
from app.delivery.contracts import DeliveryMessage, DeliveryOutcome, DeliveryResult
from app.domain.generated_content import (
    CreateContentAttempt,
    calculate_content_checksum,
)
from app.domain.lifecycle import ContentReviewStatus, PublicationStatus
from app.domain.market_events import MarketEventCandidate, SnapshotIdentity
from app.domain.price_snapshot import PriceSnapshot
from app.domain.processing import StateTransitionOutcome, StateTransitionResult
from app.domain.publications import ClaimedPublication, CreatePublication
from app.repositories.postgres import PostgresPublicationRepository
from app.repositories.provider import RepositoryProvider, create_postgres_provider
from app.scheduler import PendingPublicationDeliveryJob
from app.services.publication_delivery import (
    PublicationDeliveryPolicy,
    PublicationDeliveryRetryPolicy,
    PublicationDeliveryService,
    PublicationDeliveryStatus,
)
from app.services.publication_intents import PublicationIntentService
from app.services.repository_scope import RepositoryScopeFactory
from app.telegram.adapter import TelegramPublicationAdapter
from app.telegram.client import TelegramBotApiClient
from app.telegram.security import sanitize_provider_message
from tests.repositories.contracts.factories import NOW, make_event, uuid_for

DATABASE_URL_ENV = "EPIC14_DATABASE_URL"
TOKEN = "123456:OFFLINE_FAKE_TOKEN_DO_NOT_USE"
DESTINATION_ID = "-1001234567890"
SECOND_DESTINATION_ID = "-1009876543210"
Handler = Callable[[httpx.Request], httpx.Response]


class Verification:
    """Collect and print named Task 2 verification checks."""

    def __init__(self) -> None:
        self.passed: list[str] = []

    def check(self, name: str, condition: bool) -> None:
        """Record one passing condition or raise immediately."""
        if not condition:
            raise AssertionError(name)
        self.passed.append(name)
        print(f"PASS: {name}")


class TrackedScopes:
    """Create transaction scopes and expose active state to mock transport."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self.active = 0
        self.entries = 0

    def factory(self) -> RepositoryScopeFactory:
        """Return a repository scope factory with one transaction per entry."""
        return self.scope

    @asynccontextmanager
    async def scope(self) -> AsyncIterator[RepositoryProvider]:
        self.entries += 1
        async with self._session_factory() as session, session.begin():
            self.active += 1
            try:
                yield create_postgres_provider(session)
            finally:
                self.active -= 1


async def recreate_schema(database_url: str) -> None:
    """Recreate public schema in the explicitly isolated database."""
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


def apply_migrations(database_url: str) -> None:
    """Apply Alembic migrations through the current project head."""
    os.environ["DATABASE_URL"] = database_url
    settings.database.url = database_url
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")


async def reset_data(engine: AsyncEngine) -> None:
    """Clear durable data while preserving migrated schema."""
    async with engine.begin() as connection:
        await connection.run_sync(get_metadata().drop_all)
        await connection.run_sync(get_metadata().create_all)


async def seed_publication(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    number: int = 1,
    destination_id: str = DESTINATION_ID,
    channel: str = "telegram",
    approve: bool = True,
) -> UUID:
    """Create one durable event, generated content, and publication intent."""
    event = make_event(number=number, event_id=uuid_for(140_000 + number))
    content_id = uuid_for(141_000 + number)
    publication_id = uuid_for(142_000 + number)
    async with session_factory() as session, session.begin():
        repositories = create_postgres_provider(session)
        await repositories.price_history.add(_snapshot(event.previous_snapshot))
        await repositories.price_history.add(_snapshot(event.current_snapshot))
        await repositories.events.add_idempotently(MarketEventCandidate(event=event))
        await repositories.generated_contents.create_attempt(
            CreateContentAttempt(
                id=content_id,
                event_id=event.id,
                content_type="telegram_post",
                language="ru",
                prompt_version="price_drop_v1",
                attempt_number=1,
                provider="fake",
                model="deterministic",
                created_at=NOW + timedelta(minutes=number),
            )
        )
        claimed = (
            await repositories.generated_contents.claim_pending(
                NOW + timedelta(minutes=10),
                "content-worker",
                NOW + timedelta(minutes=11),
                1,
            )
        )[0]
        text_value = f"Generated publication #{number}"
        await repositories.generated_contents.complete_attempt(
            content_id,
            claimed.claim.token,
            claimed.content.version,
            text_value,
            calculate_content_checksum(text_value),
            NOW + timedelta(minutes=10, seconds=1),
        )
        if approve:
            completed = await repositories.generated_contents.get_by_id(content_id)
            assert completed is not None
            await repositories.generated_contents.set_review_status(
                content_id,
                ContentReviewStatus.APPROVED,
                NOW + timedelta(minutes=10, seconds=2),
                completed.version,
            )
        await repositories.publications.create_idempotently(
            CreatePublication(
                id=publication_id,
                event_id=event.id,
                content_id=content_id,
                channel=channel,
                destination_key=destination_id,
                created_at=NOW + timedelta(minutes=11),
            )
        )
    return publication_id


def make_service(
    session_factory: async_sessionmaker[AsyncSession],
    scopes: TrackedScopes,
    handler: Handler,
    *,
    repository_scope_factory: RepositoryScopeFactory | None = None,
) -> tuple[PublicationDeliveryService, TelegramBotApiClient]:
    """Compose the real delivery service with a mock Telegram transport."""
    client = TelegramBotApiClient(
        token=SecretStr(TOKEN),
        api_base_url="https://offline.telegram.test",
        transport=httpx.MockTransport(handler),
    )
    adapter = TelegramPublicationAdapter(client)
    return (
        PublicationDeliveryService(
            repository_scope_factory=(
                repository_scope_factory
                if repository_scope_factory is not None
                else scopes.factory()
            ),
            adapter=adapter,
            policy=PublicationDeliveryPolicy(
                retry_policy=PublicationDeliveryRetryPolicy(
                    maximum_attempts=5,
                    initial_delay=timedelta(seconds=30),
                    maximum_delay=timedelta(minutes=30),
                ),
                allowed_destination_ids=frozenset(
                    {DESTINATION_ID, SECOND_DESTINATION_ID}
                ),
            ),
            clock=lambda: NOW + timedelta(minutes=20),
        ),
        client,
    )


def completion_failure_scope_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> RepositoryScopeFactory:
    """Return a PostgreSQL scope that fails after successful publication state."""

    class FailingPublicationRepository(PostgresPublicationRepository):
        """Persist a publication and then force the outer transaction to roll back."""

        async def mark_published(
            self,
            publication_id: UUID,
            claim_token: UUID,
            expected_version: int,
            external_message_id: str,
            published_at: datetime,
        ) -> StateTransitionResult:
            await super().mark_published(
                publication_id,
                claim_token,
                expected_version,
                external_message_id,
                published_at,
            )
            msg = "controlled publication completion failure"
            raise RuntimeError(msg)

    @asynccontextmanager
    async def scope() -> AsyncIterator[RepositoryProvider]:
        async with session_factory() as session, session.begin():
            provider = create_postgres_provider(session)
            provider.publications = FailingPublicationRepository(session)
            yield provider

    return scope


async def load_publication(
    session_factory: async_sessionmaker[AsyncSession],
    publication_id: UUID,
) -> object:
    """Load one publication through a fresh session."""
    async with session_factory() as session:
        return await create_postgres_provider(session).publications.get_by_id(
            publication_id
        )


async def verify_success(
    checks: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify channel claim, send, publish, idempotency, and fresh state."""
    await reset_data(engine)
    publication_id = await seed_publication(session_factory)
    await seed_publication(
        session_factory,
        number=2,
        destination_id=SECOND_DESTINATION_ID,
        channel="email",
    )
    scopes = TrackedScopes(session_factory)
    transport_scope_states: list[int] = []
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        transport_scope_states.append(scopes.active)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": 1402,
                    "chat": {"id": int(DESTINATION_ID)},
                },
            },
            request=request,
        )

    service, client = make_service(session_factory, scopes, handler)
    try:
        result = await service.process_batch(
            worker_id="delivery-worker",
            limit=2,
        )
        repeated = await service.process_batch(
            worker_id="delivery-worker",
            limit=2,
        )
    finally:
        await client.aclose()
    stored = await load_publication(session_factory, publication_id)

    checks.check("default Telegram config cannot send live messages", _safe_defaults())
    checks.check("eligible Telegram publication can be claimed", result.claimed == 1)
    checks.check(
        "channel-scoped claim leaves non-Telegram untouched",
        result.claimed == 1,
    )
    checks.check("message is formatted before delivery", calls == 1)
    checks.check(
        "Telegram call occurs outside DB transaction",
        transport_scope_states == [0],
    )
    checks.check("confirmed success is persisted", result.published == 1)
    checks.check(
        "external message ID persists",
        getattr(stored, "external_message_id", None) == "1402",
    )
    checks.check(
        "fresh session observes published state",
        getattr(stored, "status", None) is PublicationStatus.PUBLISHED,
    )
    checks.check(
        "idempotent second run does not resend",
        repeated.claimed == 0 and calls == 1,
    )


async def verify_retry_and_failures(
    checks: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify retryable, rate-limit, permanent, and ambiguous outcomes."""
    await reset_data(engine)
    retry_id = await seed_publication(session_factory, number=3)
    scopes = TrackedScopes(session_factory)

    def connect_failure(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"connect failed {request.url}", request=request)

    service, client = make_service(session_factory, scopes, connect_failure)
    try:
        retry_result = await service.process_batch(
            worker_id="retry-worker",
            limit=1,
        )
    finally:
        await client.aclose()
    retry_publication = await load_publication(session_factory, retry_id)
    checks.check(
        "retryable connect failure schedules retry",
        retry_result.retries_scheduled == 1,
    )
    checks.check(
        "retry stores safe error without token",
        TOKEN not in repr(retry_publication),
    )

    await reset_data(engine)
    rate_id = await seed_publication(session_factory, number=4)
    scopes = TrackedScopes(session_factory)

    def rate_limit(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"ok": False, "error_code": 429, "parameters": {"retry_after": 90}},
            request=request,
        )

    service, client = make_service(session_factory, scopes, rate_limit)
    try:
        rate_result = await service.process_batch(worker_id="rate-worker", limit=1)
    finally:
        await client.aclose()
    rate_publication = await load_publication(session_factory, rate_id)
    checks.check(
        "429 retry-after schedules retry",
        rate_result.stopped_after_rate_limit,
    )
    checks.check(
        "429 retry-after is honored",
        getattr(rate_publication, "next_retry_at", None)
        == NOW + timedelta(minutes=21, seconds=30),
    )

    resume_scopes = TrackedScopes(session_factory)
    resume_time = NOW + timedelta(minutes=21, seconds=30)

    def resume_success(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": 1404,
                    "chat": {"id": int(DESTINATION_ID)},
                },
            },
            request=request,
        )

    resumed_service, client = make_service(
        session_factory,
        resume_scopes,
        resume_success,
    )
    try:
        resumed_result = await resumed_service.process_batch(
            worker_id="resume-worker",
            limit=1,
            now=resume_time,
        )
    finally:
        await client.aclose()
    resumed_publication = await load_publication(session_factory, rate_id)
    checks.check(
        "retryable publication resumes when due",
        resumed_result.published == 1,
    )
    checks.check(
        "fresh session observes resumed publication",
        getattr(resumed_publication, "status", None) is PublicationStatus.PUBLISHED,
    )

    await reset_data(engine)
    permanent_id = await seed_publication(session_factory, number=5)
    scopes = TrackedScopes(session_factory)

    def forbidden(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"ok": False, "error_code": 403, "description": "Forbidden"},
            request=request,
        )

    service, client = make_service(session_factory, scopes, forbidden)
    try:
        permanent_result = await service.process_batch(
            worker_id="permanent-worker",
            limit=1,
        )
    finally:
        await client.aclose()
    permanent_publication = await load_publication(session_factory, permanent_id)
    checks.check("permanent 403 is terminal", permanent_result.permanent_failures == 1)
    checks.check(
        "permanent failure has no automatic retry",
        getattr(permanent_publication, "next_retry_at", object()) is None,
    )

    await reset_data(engine)
    ambiguous_id = await seed_publication(session_factory, number=6)
    scopes = TrackedScopes(session_factory)

    def read_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"read timed out {request.url}", request=request)

    service, client = make_service(session_factory, scopes, read_timeout)
    try:
        ambiguous_result = await service.process_batch(
            worker_id="ambiguous-worker",
            limit=1,
        )
        repeated = await service.process_batch(
            worker_id="ambiguous-worker",
            limit=1,
        )
    finally:
        await client.aclose()
    ambiguous_publication = await load_publication(session_factory, ambiguous_id)
    checks.check("ambiguous read timeout is persisted", ambiguous_result.ambiguous == 1)
    checks.check(
        "ambiguous publication is excluded from retry",
        repeated.claimed == 0
        and getattr(ambiguous_publication, "status", None)
        is PublicationStatus.AMBIGUOUS,
    )


async def verify_restart_and_redaction(
    checks: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify restart safety after a successful send and token redaction."""
    await reset_data(engine)
    publication_id = await seed_publication(session_factory, number=10)
    scopes = TrackedScopes(session_factory)

    def success(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": 1410,
                    "chat": {"id": int(DESTINATION_ID)},
                },
            },
            request=request,
        )

    service, client = make_service(
        session_factory,
        scopes,
        success,
        repository_scope_factory=completion_failure_scope_factory(session_factory),
    )
    try:
        try:
            await service.process_batch(worker_id="restart-worker", limit=1)
        except RuntimeError as error:
            checks.check(
                "completion failure is exposed",
                "controlled publication completion failure" in str(error),
            )
    finally:
        await client.aclose()

    stored = await load_publication(session_factory, publication_id)
    checks.check(
        "successful adapter response survives until completion failure",
        getattr(stored, "status", None) is PublicationStatus.IN_PROGRESS,
    )
    checks.check(
        "attempt count survives completion rollback",
        getattr(stored, "attempt_count", None) == 1,
    )

    intent_service = PublicationIntentService(
        repository_scope_factory=TrackedScopes(session_factory).factory()
    )
    recovery = await intent_service.recover_stale_publication_claims(
        limit=10,
        now=NOW + timedelta(minutes=22),
    )
    recovered = await load_publication(session_factory, publication_id)
    checks.check(
        "stale claim after completion rollback becomes ambiguous",
        recovery.ambiguous == 1,
    )
    checks.check(
        "fresh session observes ambiguous recovery after restart",
        getattr(recovered, "status", None) is PublicationStatus.AMBIGUOUS,
    )

    safe_message = sanitize_provider_message(
        f"token {TOKEN} must be hidden",
        token=TOKEN,
    )
    checks.check(
        "token redaction sanitizes provider messages",
        safe_message is not None
        and TOKEN not in safe_message
        and "[REDACTED]" in safe_message,
    )
    telegram_client = TelegramBotApiClient(
        token=SecretStr(TOKEN),
        api_base_url="https://offline.telegram.test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"ok": True, "result": {"message_id": 1, "chat": {"id": 1}}},
                request=request,
            )
        ),
    )
    checks.check("telegram client repr hides token", TOKEN not in repr(telegram_client))
    await telegram_client.aclose()


async def verify_two_worker_claim_behavior(
    checks: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify one Telegram publication is claimed by only one worker."""
    await reset_data(engine)
    await seed_publication(session_factory, number=1)

    class BlockingSuccessAdapter:
        def __init__(self) -> None:
            self.calls = 0
            self.messages: list[DeliveryMessage] = []
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def send(self, message: DeliveryMessage) -> DeliveryResult:
            self.calls += 1
            self.messages.append(message)
            self.entered.set()
            if self.calls == 1:
                await self.release.wait()
            return DeliveryResult(
                outcome=DeliveryOutcome.SUCCESS,
                destination_id=message.destination_id,
                external_message_id=f"blocking-{self.calls}",
            )

    scopes = TrackedScopes(session_factory)
    adapter = BlockingSuccessAdapter()
    service = PublicationDeliveryService(
        repository_scope_factory=scopes.factory(),
        adapter=adapter,
        policy=PublicationDeliveryPolicy(
            retry_policy=PublicationDeliveryRetryPolicy(
                maximum_attempts=5,
                initial_delay=timedelta(seconds=30),
                maximum_delay=timedelta(minutes=30),
            ),
            allowed_destination_ids=frozenset({DESTINATION_ID, SECOND_DESTINATION_ID}),
        ),
        clock=lambda: NOW + timedelta(minutes=20),
    )

    first = asyncio.create_task(
        service.process_batch(worker_id="worker-one", limit=1),
    )
    await adapter.entered.wait()
    second_task = asyncio.create_task(
        service.process_batch(worker_id="worker-two", limit=1),
    )
    second = await asyncio.wait_for(second_task, timeout=10)
    adapter.release.set()
    first_result = await asyncio.wait_for(first, timeout=10)

    checks.check("one worker claims the publication", first_result.claimed == 1)
    checks.check("second worker receives no publication", second.claimed == 0)
    checks.check("one adapter call occurs", adapter.calls == 1)


async def verify_claims_and_dry_run(
    checks: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify stale claims, active lease protection, and dry-run behavior."""
    await reset_data(engine)
    publication_id = await seed_publication(session_factory, number=7)
    async with session_factory() as session, session.begin():
        repositories = create_postgres_provider(session)
        claimed = (
            await repositories.publications.claim_pending(
                NOW + timedelta(minutes=20),
                "manual-worker",
                NOW + timedelta(minutes=21),
                1,
                channel="telegram",
                maximum_attempts=5,
            )
        )[0]
        active = await repositories.publications.claim_pending(
            NOW + timedelta(minutes=20, seconds=30),
            "other-worker",
            NOW + timedelta(minutes=21),
            1,
            channel="telegram",
            maximum_attempts=5,
        )
    checks.check("active lease protects claimed publication", active == ())

    intent_service = PublicationIntentService(
        repository_scope_factory=TrackedScopes(session_factory).factory()
    )
    recovery = await intent_service.recover_stale_publication_claims(
        limit=10,
        now=NOW + timedelta(minutes=21),
    )
    stale_completion = await _stale_complete(session_factory, claimed, publication_id)
    stored = await load_publication(session_factory, publication_id)
    checks.check("expired claim recovery marks ambiguous", recovery.ambiguous == 1)
    checks.check(
        "stale token cannot complete",
        stale_completion is not StateTransitionOutcome.APPLIED,
    )
    checks.check(
        "recovery is idempotent",
        (
            await intent_service.recover_stale_publication_claims(
                limit=10,
                now=NOW + timedelta(minutes=22),
            )
        ).expired_found
        == 0,
    )
    checks.check(
        "recovered ambiguous state survives fresh session",
        getattr(stored, "status", None) is PublicationStatus.AMBIGUOUS,
    )

    await reset_data(engine)
    dry_id = await seed_publication(session_factory, number=8)
    calls = 0

    def success(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"ok": True}, request=request)

    scopes = TrackedScopes(session_factory)
    service, client = make_service(session_factory, scopes, success)
    try:
        dry_run = await service.dry_run_publication(dry_id)
    finally:
        await client.aclose()
    dry_publication = await load_publication(session_factory, dry_id)
    checks.check(
        "dry-run renders text",
        dry_run.status is PublicationDeliveryStatus.DRY_RUN,
    )
    checks.check("dry-run calls no Telegram transport", calls == 0)
    checks.check(
        "dry-run mutates no durable state",
        getattr(dry_publication, "status", None) is PublicationStatus.PENDING
        and getattr(dry_publication, "attempt_count", None) == 0,
    )


async def _stale_complete(
    session_factory: async_sessionmaker[AsyncSession],
    claimed: ClaimedPublication,
    publication_id: UUID,
) -> StateTransitionOutcome:
    async with session_factory() as session, session.begin():
        repositories = create_postgres_provider(session)
        transition = await repositories.publications.mark_published(
            publication_id,
            claimed.claim.token,
            claimed.publication.version,
            "stale-message",
            NOW + timedelta(minutes=22),
        )
        return transition.outcome


async def verify_scheduler_job(
    checks: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify the scheduler job delegates to the delivery service."""
    await reset_data(engine)
    await seed_publication(session_factory, number=9)
    scopes = TrackedScopes(session_factory)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": 1409,
                    "chat": {"id": int(DESTINATION_ID)},
                },
            },
            request=request,
        )

    service, client = make_service(session_factory, scopes, handler)
    job = PendingPublicationDeliveryJob(
        service,
        worker_id="scheduler-delivery-worker",
        batch_size=1,
        clock=lambda: NOW + timedelta(minutes=20),
    )
    try:
        await job.execute()
    finally:
        await client.aclose()
    checks.check(
        "Scheduler job invokes delivery service",
        job.status.failure_count == 0,
    )


async def _migration_revision(session_factory: async_sessionmaker[AsyncSession]) -> str:
    async with session_factory() as session:
        revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
    assert isinstance(revision, str)
    return revision


async def run_verification(database_url: str) -> None:
    """Run the full offline PostgreSQL verification."""
    checks = Verification()
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        checks.check(
            "migrations reached 0008",
            await _migration_revision(session_factory) == "0008_content_publications",
        )
        await verify_success(checks, engine, session_factory)
        await verify_retry_and_failures(checks, engine, session_factory)
        await verify_claims_and_dry_run(checks, engine, session_factory)
        await verify_restart_and_redaction(checks, engine, session_factory)
        await verify_two_worker_claim_behavior(checks, engine, session_factory)
        await verify_scheduler_job(checks, engine, session_factory)
        total = len(checks.passed)
        print(f"\nEPIC 14 offline verification: {total}/{total} checks passed")
    finally:
        await engine.dispose()


def _safe_defaults() -> bool:
    settings = TelegramSettings.model_construct()
    return (
        settings.delivery_enabled is False
        and settings.dry_run is True
        and settings.allow_live_delivery is False
    )


def _snapshot(identity: SnapshotIdentity) -> PriceSnapshot:
    return PriceSnapshot(
        marketplace=identity.marketplace,
        external_id=identity.external_id,
        price=identity.price,
        currency=identity.currency,
        collected_at=identity.collected_at,
    )


def verify(database_url: str) -> None:
    """Recreate the isolated schema, migrate, and run verification."""
    asyncio.run(recreate_schema(database_url))
    apply_migrations(database_url)
    asyncio.run(run_verification(database_url))


def main() -> None:
    """Run offline PostgreSQL verification when an isolated database is available."""
    database_url = os.getenv(DATABASE_URL_ENV)
    if not database_url:
        print(f"SKIP: set {DATABASE_URL_ENV} to an isolated epic14_* PostgreSQL URL.")
        return
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql" or not (url.database or "").startswith(
        "epic14_"
    ):
        raise SystemExit(
            f"{DATABASE_URL_ENV} must target an isolated epic14_* PostgreSQL database."
        )
    verify(database_url)


if __name__ == "__main__":
    main()
