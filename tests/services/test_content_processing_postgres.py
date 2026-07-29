from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.ai.provider import AIProvider
from app.database.metadata import get_metadata
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
from app.services.content_generator import ContentGenerator
from app.services.content_processing import (
    ContentGenerationDescriptor,
    ContentGenerationProcessingService,
    ContentProcessingBatchResult,
    ContentProcessingErrorCategory,
    ContentRetryPolicy,
)
from app.services.publication_intents import (
    PublicationIntentService,
    PublicationTarget,
)
from app.services.repository_scope import RepositoryScopeFactory
from tests.repositories.contracts.factories import NOW, make_event, run_async, uuid_for

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


class TrackedPostgresScopes:
    """Create real transaction scopes and expose active-scope state."""

    def __init__(self, *, fail_on_exit_entry: int | None = None) -> None:
        self.active = 0
        self.entries = 0
        self.fail_on_exit_entry = fail_on_exit_entry

    def factory(self) -> RepositoryScopeFactory:
        return self.scope

    @asynccontextmanager
    async def scope(self) -> AsyncIterator[RepositoryProvider]:
        self.entries += 1
        entry = self.entries
        async with _session_factory()() as session, session.begin():
            self.active += 1
            try:
                yield create_postgres_provider(session)
                if entry == self.fail_on_exit_entry:
                    msg = "simulated completion transaction failure"
                    raise RuntimeError(msg)
            finally:
                self.active -= 1


class RecordingProvider(AIProvider):
    """Deterministic fake provider with transaction-boundary assertions."""

    def __init__(self, scopes: TrackedPostgresScopes, responses: list[object]) -> None:
        self.scopes = scopes
        self.responses = responses
        self.scope_states: list[int] = []
        self.calls = 0

    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        del system_prompt, user_prompt
        self.scope_states.append(self.scopes.active)
        response = self.responses[self.calls]
        self.calls += 1
        if isinstance(response, Exception):
            raise response
        assert isinstance(response, str)
        return response


def _service(
    scopes: TrackedPostgresScopes,
    provider: AIProvider,
) -> ContentGenerationProcessingService:
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
        publication_target=PublicationTarget("preview", "postgres-verification"),
    )


def test_postgres_content_success_survives_fresh_session_and_is_idempotent() -> None:
    run_async(_reset_database())
    event = make_event()
    run_async(_seed_scored_event(event))
    scopes = TrackedPostgresScopes()
    ai = RecordingProvider(scopes, ["Durable generated content"])
    service = _service(scopes, ai)

    first = run_async(
        service.process_pending(
            worker_id="content-worker",
            limit=1,
            now=NOW + timedelta(minutes=20),
        )
    )
    second = run_async(
        service.process_pending(
            worker_id="content-worker",
            limit=1,
            now=NOW + timedelta(minutes=21),
        )
    )
    contents, publications = run_async(_load_event_work(event.id))

    assert first.generated == 1
    assert first.publications_created == 1
    assert second.claimed == 0
    assert ai.calls == 1
    assert ai.scope_states == [0]
    assert len(contents) == 1
    assert contents[0].content_text == "Durable generated content"
    assert len(publications) == 1
    assert publications[0].status is PublicationStatus.PENDING


def test_postgres_two_workers_generate_one_logical_attempt() -> None:
    run_async(_reset_database())
    event = make_event()
    run_async(_seed_scored_event(event))
    first_scopes = TrackedPostgresScopes()
    second_scopes = TrackedPostgresScopes()
    first_ai = RecordingProvider(first_scopes, ["Worker one"])
    second_ai = RecordingProvider(second_scopes, ["Worker two"])

    async def process_both() -> tuple[
        ContentProcessingBatchResult,
        ContentProcessingBatchResult,
    ]:
        return await asyncio.gather(
            _service(first_scopes, first_ai).process_pending(
                worker_id="worker-one",
                limit=1,
                now=NOW + timedelta(minutes=20),
            ),
            _service(second_scopes, second_ai).process_pending(
                worker_id="worker-two",
                limit=1,
                now=NOW + timedelta(minutes=20),
            ),
        )

    run_async(process_both())
    contents, publications = run_async(_load_event_work(event.id))

    assert first_ai.calls + second_ai.calls == 1
    assert len(contents) == 1
    assert contents[0].generation_status is ContentGenerationStatus.GENERATED
    assert len(publications) == 1


def test_postgres_generation_retry_survives_fresh_service() -> None:
    run_async(_reset_database())
    event = make_event()
    run_async(_seed_scored_event(event))
    first_scopes = TrackedPostgresScopes()
    failed = run_async(
        _service(
            first_scopes,
            RecordingProvider(first_scopes, [RuntimeError("temporary")]),
        ).process_pending(
            worker_id="worker-one",
            limit=1,
            now=NOW + timedelta(minutes=20),
        )
    )
    second_scopes = TrackedPostgresScopes()
    recovered = run_async(
        _service(
            second_scopes,
            RecordingProvider(second_scopes, ["Retry success"]),
        ).process_pending(
            worker_id="worker-two",
            limit=1,
            now=NOW + timedelta(minutes=20, seconds=5),
        )
    )
    contents, publications = run_async(_load_event_work(event.id))

    assert failed.items[0].error_category is ContentProcessingErrorCategory.TRANSIENT
    assert recovered.generated == 1
    assert tuple(content.attempt_number for content in contents) == (1, 2)
    assert len(publications) == 1


def test_postgres_completion_rollback_keeps_claim_and_no_publication() -> None:
    run_async(_reset_database())
    event = make_event()
    run_async(_seed_scored_event(event))
    scopes = TrackedPostgresScopes(fail_on_exit_entry=2)
    result = run_async(
        _service(
            scopes,
            RecordingProvider(scopes, ["Rolled back content"]),
        ).process_pending(
            worker_id="worker",
            limit=1,
            now=NOW + timedelta(minutes=20),
        )
    )
    contents, publications = run_async(_load_event_work(event.id))

    assert result.items[0].error_category is ContentProcessingErrorCategory.PERSISTENCE
    assert contents[0].generation_status is ContentGenerationStatus.IN_PROGRESS
    assert contents[0].content_text is None
    assert publications == ()


def test_postgres_stale_generation_and_publication_recovery() -> None:
    run_async(_reset_database())
    event = make_event()
    run_async(_seed_scored_event(event))
    run_async(_seed_expired_claims(event))
    scopes = TrackedPostgresScopes()
    provider = RecordingProvider(scopes, [])
    content_service = _service(scopes, provider)
    publication_service = PublicationIntentService(
        repository_scope_factory=scopes.factory()
    )

    content = run_async(
        content_service.recover_stale_generation_claims(
            limit=10,
            now=NOW + timedelta(minutes=21),
        )
    )
    publication = run_async(
        publication_service.recover_stale_publication_claims(
            limit=10,
            now=NOW + timedelta(minutes=21),
        )
    )
    repeated_content = run_async(
        content_service.recover_stale_generation_claims(
            limit=10,
            now=NOW + timedelta(minutes=22),
        )
    )
    repeated_publication = run_async(
        publication_service.recover_stale_publication_claims(
            limit=10,
            now=NOW + timedelta(minutes=22),
        )
    )

    assert content.abandoned == 1
    assert publication.ambiguous == 1
    assert repeated_content.expired_found == 0
    assert repeated_publication.expired_found == 0


async def _reset_database() -> None:
    async with _engine().begin() as connection:
        await connection.run_sync(get_metadata().drop_all)
        await connection.run_sync(get_metadata().create_all)


async def _seed_scored_event(event: PriceDropMarketEvent) -> None:
    async with _session_factory()() as session, session.begin():
        provider = create_postgres_provider(session)
        await provider.price_history.add(_snapshot(event.previous_snapshot))
        await provider.price_history.add(_snapshot(event.current_snapshot))
        await provider.events.add_idempotently(MarketEventCandidate(event=event))
        claimed = (
            await provider.events.claim_pending(
                NOW + timedelta(minutes=10),
                "score-worker",
                NOW + timedelta(minutes=11),
                1,
            )
        )[0]
        await provider.events.mark_scored(
            event.id,
            claimed.claim.token,
            claimed.event.version,
            80,
            NOW + timedelta(minutes=10, seconds=1),
        )


async def _load_event_work(
    event_id: UUID,
) -> tuple[tuple[GeneratedContentAttempt, ...], tuple[Publication, ...]]:
    async with _session_factory()() as session:
        provider = create_postgres_provider(session)
        return (
            tuple(await provider.generated_contents.list_for_event(event_id)),
            tuple(await provider.publications.list_for_event(event_id)),
        )


async def _seed_expired_claims(event: PriceDropMarketEvent) -> None:
    async with _session_factory()() as session, session.begin():
        provider = create_postgres_provider(session)
        stale_command = CreateContentAttempt(
            id=uuid_for(50_001),
            event_id=event.id,
            content_type="stale_content",
            language="ru",
            prompt_version="price_drop_v1",
            attempt_number=1,
            provider="fake",
            model="deterministic",
            created_at=NOW + timedelta(minutes=20),
        )
        await provider.generated_contents.create_attempt(stale_command)
        await provider.generated_contents.claim_pending(
            NOW + timedelta(minutes=20),
            "stale-content-worker",
            NOW + timedelta(minutes=21),
            1,
        )

        publication_source = CreateContentAttempt(
            id=uuid_for(50_002),
            event_id=event.id,
            content_type="publication_source",
            language="ru",
            prompt_version="price_drop_v1",
            attempt_number=1,
            provider="fake",
            model="deterministic",
            created_at=NOW + timedelta(minutes=20, seconds=1),
        )
        await provider.generated_contents.create_attempt(publication_source)
        claimed_source = (
            await provider.generated_contents.claim_pending(
                NOW + timedelta(minutes=20, seconds=1),
                "publication-content-worker",
                NOW + timedelta(minutes=21, seconds=1),
                1,
            )
        )[0]
        content_text = "Seed publication content"
        await provider.generated_contents.complete_attempt(
            publication_source.id,
            claimed_source.claim.token,
            claimed_source.content.version,
            content_text,
            calculate_content_checksum(content_text),
            NOW + timedelta(minutes=20, seconds=10),
        )
        publication = CreatePublication(
            id=uuid_for(50_003),
            event_id=event.id,
            content_id=publication_source.id,
            channel="preview",
            destination_key="stale-publication",
            created_at=NOW + timedelta(minutes=20, seconds=11),
        )
        await provider.publications.create_idempotently(publication)
        await provider.publications.claim_pending(
            NOW + timedelta(minutes=20, seconds=12),
            "stale-publication-worker",
            NOW + timedelta(minutes=21),
            1,
        )


def _snapshot(identity: SnapshotIdentity) -> PriceSnapshot:
    return PriceSnapshot(
        marketplace=identity.marketplace,
        external_id=identity.external_id,
        price=identity.price,
        currency=identity.currency,
        collected_at=identity.collected_at,
    )


def _engine() -> AsyncEngine:
    assert _ENGINE is not None
    return _ENGINE


def _session_factory() -> async_sessionmaker[AsyncSession]:
    assert _SESSION_FACTORY is not None
    return _SESSION_FACTORY
