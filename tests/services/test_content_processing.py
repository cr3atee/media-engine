from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta

from app.ai.provider import AIProvider
from app.config.settings import ContentProcessingSettings
from app.domain.generated_content import CreateContentAttempt
from app.domain.lifecycle import (
    ContentGenerationStatus,
    PublicationStatus,
)
from app.domain.market_events import MarketEventCandidate
from app.domain.publications import CreatePublication
from app.insights.scoring import EventScorer
from app.repositories.provider import RepositoryProvider, create_memory_provider
from app.scheduler import (
    PendingContentGenerationJob,
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
from app.services.event_processing import EventProcessingService
from app.services.publication_intents import (
    PublicationIntentService,
    PublicationRecoveryResult,
    PublicationTarget,
)
from app.services.repository_scope import RepositoryScopeFactory
from tests.repositories.contracts.factories import NOW, make_event, run_async, uuid_for

_DEFAULT_TARGET = PublicationTarget("preview", "test-destination")


class ScopeTracker:
    """Track whether a repository scope is active during external work."""

    def __init__(self, provider: RepositoryProvider) -> None:
        self.provider = provider
        self.active = 0
        self.entries = 0

    def factory(self) -> RepositoryScopeFactory:
        return self.scope

    @asynccontextmanager
    async def scope(self) -> AsyncIterator[RepositoryProvider]:
        self.entries += 1
        self.active += 1
        try:
            yield self.provider
        finally:
            self.active -= 1


class RecordingProvider(AIProvider):
    """Deterministic provider that records transaction-boundary state."""

    def __init__(self, tracker: ScopeTracker, responses: list[object]) -> None:
        self.tracker = tracker
        self.responses = responses
        self.scope_states: list[int] = []
        self.calls = 0

    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        del system_prompt, user_prompt
        self.scope_states.append(self.tracker.active)
        response = self.responses[self.calls]
        self.calls += 1
        if isinstance(response, Exception):
            raise response
        assert isinstance(response, str)
        return response


async def _scored_provider() -> tuple[RepositoryProvider, ScopeTracker]:
    provider = create_memory_provider()
    tracker = ScopeTracker(provider)
    event = make_event()
    await provider.events.add_idempotently(MarketEventCandidate(event=event))
    service = EventProcessingService(
        repository_scope_factory=tracker.factory(),
        scorer=EventScorer(),
    )
    result = await service.process_pending(
        worker_id="score-worker",
        limit=1,
        now=NOW + timedelta(minutes=10),
    )
    assert result.scored == 1
    return provider, tracker


def _content_service(
    tracker: ScopeTracker,
    provider: AIProvider,
    *,
    publication_target: PublicationTarget | None = _DEFAULT_TARGET,
) -> ContentGenerationProcessingService:
    publication_service = PublicationIntentService(
        repository_scope_factory=tracker.factory(),
        publication_id_factory=lambda: uuid_for(40_001),
    )
    content_ids = iter((uuid_for(30_001), uuid_for(30_002), uuid_for(30_003)))
    return ContentGenerationProcessingService(
        repository_scope_factory=tracker.factory(),
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
        publication_target=publication_target,
        content_id_factory=lambda: next(content_ids),
    )


async def _content_success_is_durable_idempotent_and_outside_scope() -> None:
    provider, tracker = await _scored_provider()
    ai = RecordingProvider(tracker, ["Generated publication"])
    service = _content_service(tracker, ai)

    first = await service.process_pending(
        worker_id="content-worker",
        limit=1,
        now=NOW + timedelta(minutes=20),
    )
    second = await service.process_pending(
        worker_id="content-worker",
        limit=1,
        now=NOW + timedelta(minutes=21),
    )
    event = (await provider.events.list_content_eligible(1))[0]
    contents = await provider.generated_contents.list_for_event(event.id)
    publications = await provider.publications.list_for_event(event.id)

    assert first.generated == 1
    assert first.publications_created == 1
    assert second.claimed == 0
    assert ai.calls == 1
    assert ai.scope_states == [0]
    assert len(contents) == 1
    assert contents[0].generation_status is ContentGenerationStatus.GENERATED
    assert contents[0].content_text == "Generated publication"
    assert len(publications) == 1
    assert publications[0].status is PublicationStatus.PENDING


async def _transient_failure_creates_new_retry_attempt_and_then_succeeds() -> None:
    provider, tracker = await _scored_provider()
    ai = RecordingProvider(
        tracker,
        [RuntimeError("temporary provider failure"), "Recovered publication"],
    )
    service = _content_service(tracker, ai)

    failed = await service.process_pending(
        worker_id="content-worker",
        limit=1,
        now=NOW + timedelta(minutes=20),
    )
    before_due = await service.process_pending(
        worker_id="content-worker",
        limit=1,
        now=NOW + timedelta(minutes=20, seconds=4),
    )
    recovered = await service.process_pending(
        worker_id="content-worker",
        limit=1,
        now=NOW + timedelta(minutes=20, seconds=5),
    )
    event = (await provider.events.list_content_eligible(1))[0]
    contents = await provider.generated_contents.list_for_event(event.id)

    assert failed.retry_scheduled == 1
    assert failed.items[0].error_category is ContentProcessingErrorCategory.TRANSIENT
    assert before_due.claimed == 0
    assert recovered.generated == 1
    assert tuple(item.attempt_number for item in contents) == (1, 2)
    assert contents[0].generation_status is ContentGenerationStatus.FAILED
    assert contents[1].generation_status is ContentGenerationStatus.GENERATED
    assert ai.scope_states == [0, 0]


async def _empty_generated_text_is_permanent_and_creates_no_publication() -> None:
    provider, tracker = await _scored_provider()
    service = _content_service(tracker, RecordingProvider(tracker, ["  "]))

    result = await service.process_pending(
        worker_id="content-worker",
        limit=1,
        now=NOW + timedelta(minutes=20),
    )
    event = (await provider.events.list_content_eligible(1))[0]

    assert (
        result.items[0].error_category is ContentProcessingErrorCategory.PERMANENT_INPUT
    )
    assert result.items[0].next_retry_at is None
    assert await provider.publications.list_for_event(event.id) == ()


async def _content_can_complete_without_publication_target() -> None:
    provider, tracker = await _scored_provider()
    service = _content_service(
        tracker,
        RecordingProvider(tracker, ["Generated without destination"]),
        publication_target=None,
    )

    result = await service.process_pending(
        worker_id="content-worker",
        limit=1,
        now=NOW + timedelta(minutes=20),
    )
    event = (await provider.events.list_content_eligible(1))[0]

    assert result.generated == 1
    assert result.publications_created == 0
    assert await provider.publications.list_for_event(event.id) == ()


async def _stale_content_and_publication_recovery_are_idempotent() -> None:
    provider, tracker = await _scored_provider()
    event = (await provider.events.list_content_eligible(1))[0]
    command = CreateContentAttempt(
        id=uuid_for(30_010),
        event_id=event.id,
        content_type="telegram_post",
        language="ru",
        prompt_version="price_drop_v1",
        attempt_number=1,
        provider="fake",
        model="deterministic",
        created_at=NOW + timedelta(minutes=20),
    )
    await provider.generated_contents.create_attempt(command)
    await provider.generated_contents.claim_pending(
        NOW + timedelta(minutes=20),
        "content-worker",
        NOW + timedelta(minutes=21),
        1,
    )
    content_service = _content_service(tracker, RecordingProvider(tracker, []))

    recovered = await content_service.recover_stale_generation_claims(
        limit=10,
        now=NOW + timedelta(minutes=21),
    )
    repeated = await content_service.recover_stale_generation_claims(
        limit=10,
        now=NOW + timedelta(minutes=22),
    )

    assert recovered.abandoned == 1
    assert repeated.expired_found == 0

    publication = CreatePublication(
        id=uuid_for(40_010),
        event_id=event.id,
        content_id=command.id,
        channel="preview",
        destination_key="test",
        created_at=NOW + timedelta(minutes=22),
    )
    await provider.publications.create_idempotently(publication)
    await provider.publications.claim_pending(
        NOW + timedelta(minutes=22),
        "publication-worker",
        NOW + timedelta(minutes=23),
        1,
    )
    publication_service = PublicationIntentService(
        repository_scope_factory=tracker.factory()
    )
    publication_recovered = await publication_service.recover_stale_publication_claims(
        limit=10,
        now=NOW + timedelta(minutes=23),
    )
    publication_repeated = await publication_service.recover_stale_publication_claims(
        limit=10,
        now=NOW + timedelta(minutes=24),
    )
    stored = await provider.publications.get_by_id(publication.id)

    assert publication_recovered.ambiguous == 1
    assert publication_repeated.expired_found == 0
    assert stored is not None
    assert stored.status is PublicationStatus.AMBIGUOUS


@dataclass(slots=True)
class RecordingContentRunner:
    """Record Scheduler delegation without repository or AI dependencies."""

    processing_calls: int = 0
    recovery_calls: int = 0

    async def process_pending(self, **kwargs: object) -> object:
        assert kwargs["limit"] == 2
        self.processing_calls += 1
        return object()

    async def recover_stale_generation_claims(self, **kwargs: object) -> object:
        assert kwargs["limit"] == 3
        self.recovery_calls += 1
        return object()


@dataclass(slots=True)
class RecordingPublicationRunner:
    recovery_calls: int = 0

    async def recover_stale_publication_claims(self, **kwargs: object) -> object:
        assert kwargs["limit"] == 4
        self.recovery_calls += 1
        return PublicationRecoveryResult(4, 0, 0, 0)


async def _scheduler_content_jobs_only_delegate() -> None:
    content = RecordingContentRunner()
    publication = RecordingPublicationRunner()
    jobs = (
        PendingContentGenerationJob(
            content,
            worker_id="worker",
            batch_size=2,
            clock=lambda: NOW,
        ),
        StaleContentClaimRecoveryJob(content, batch_size=3, clock=lambda: NOW),
        StalePublicationClaimRecoveryJob(
            publication,
            batch_size=4,
            clock=lambda: NOW,
        ),
    )

    for job in jobs:
        await job.execute()

    assert content.processing_calls == 1
    assert content.recovery_calls == 1
    assert publication.recovery_calls == 1
    assert all(job.status.failure_count == 0 for job in jobs)


def test_content_success_is_durable_idempotent_and_outside_scope() -> None:
    run_async(_content_success_is_durable_idempotent_and_outside_scope())


def test_transient_failure_creates_new_retry_attempt_and_then_succeeds() -> None:
    run_async(_transient_failure_creates_new_retry_attempt_and_then_succeeds())


def test_empty_generated_text_is_permanent_and_creates_no_publication() -> None:
    run_async(_empty_generated_text_is_permanent_and_creates_no_publication())


def test_content_can_complete_without_publication_target() -> None:
    run_async(_content_can_complete_without_publication_target())


def test_stale_content_and_publication_recovery_are_idempotent() -> None:
    run_async(_stale_content_and_publication_recovery_are_idempotent())


def test_scheduler_content_jobs_only_delegate() -> None:
    run_async(_scheduler_content_jobs_only_delegate())


def test_content_processing_configuration_defaults_are_safe() -> None:
    settings = ContentProcessingSettings.model_construct()

    assert settings.maximum_attempts == 5
    assert settings.initial_retry_seconds == 30
    assert settings.maximum_retry_seconds == 1800
    assert settings.publication_channel == ""
    assert settings.publication_destination_key == ""
