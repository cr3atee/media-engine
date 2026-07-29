from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any

from app.config.settings import EventProcessingSettings
from app.domain.events import BaseEvent
from app.domain.lifecycle import ScoringStatus
from app.domain.market_events import MarketEventCandidate, PriceDropMarketEvent
from app.domain.processing import StateTransitionOutcome
from app.insights.scoring import EventScorer
from app.repositories.memory import MemoryMarketEventRepository
from app.repositories.provider import RepositoryProvider, create_memory_provider
from app.scheduler import (
    JobExecutionState,
    MarketEventScoringJob,
    SchedulerService,
    StaleScoringClaimRecoveryJob,
)
from app.services.event_processing import (
    EventProcessingBatchResult,
    EventProcessingErrorCategory,
    EventProcessingService,
    ScoringRetryPolicy,
    StaleClaimRecoveryResult,
)
from app.services.event_processing_errors import PermanentEventProcessingError
from app.services.market_event_scoring_adapter import (
    MarketEventScoringAdapter,
    PriceDropScoringInput,
)
from app.services.repository_scope import RepositoryScopeFactory
from tests.repositories.contracts.factories import (
    NOW,
    SequentialUuidFactory,
    make_event,
)


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run one async service scenario without an external pytest plugin."""
    return asyncio.run(awaitable)


class ScopeTracker:
    """Expose whether deterministic scoring runs inside a repository scope."""

    def __init__(self, provider: RepositoryProvider) -> None:
        self.provider = provider
        self.active = 0
        self.entries = 0

    def factory(self) -> RepositoryScopeFactory:
        """Return a reusable tracked memory repository scope."""

        @asynccontextmanager
        async def scope() -> AsyncIterator[RepositoryProvider]:
            self.active += 1
            self.entries += 1
            try:
                yield self.provider
            finally:
                self.active -= 1

        return scope


class ScopeAssertingScorer(EventScorer):
    """Use the current scoring algorithm and assert transaction separation."""

    def __init__(self, tracker: ScopeTracker) -> None:
        self._tracker = tracker
        self.calls = 0

    def score(self, event: BaseEvent) -> int:
        """Score only when no repository scope is active."""
        assert self._tracker.active == 0
        self.calls += 1
        return super().score(event)


class RaisingScorer(EventScorer):
    """Raise one configured deterministic test exception."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def score(self, event: BaseEvent) -> int:
        """Raise without exposing exception contents to persistence policy."""
        del event
        raise self._exc


class SelectiveScorer(EventScorer):
    """Fail one offer while scoring all unrelated events normally."""

    def score(self, event: BaseEvent) -> int:
        """Fail only the first deterministic event."""
        if isinstance(event, PriceDropScoringInput) and event.external_id == "offer-1":
            msg = "temporary first-event failure"
            raise RuntimeError(msg)
        return super().score(event)


class PermanentlyFailingAdapter(MarketEventScoringAdapter):
    """Represent malformed durable input at the adapter boundary."""

    def adapt(self, event: PriceDropMarketEvent) -> PriceDropScoringInput:
        """Reject the event as non-retryable input."""
        del event
        msg = "unsupported durable payload"
        raise PermanentEventProcessingError(msg)


def make_tracked_provider() -> tuple[RepositoryProvider, ScopeTracker]:
    """Create a deterministic event provider and tracked scope."""
    provider = create_memory_provider()
    provider.events = MemoryMarketEventRepository(
        claim_token_factory=SequentialUuidFactory(80_000)
    )
    return provider, ScopeTracker(provider)


async def add_event(provider: RepositoryProvider, *, number: int = 1) -> None:
    """Persist one pending event through the repository contract."""
    await provider.events.add_idempotently(
        MarketEventCandidate(event=make_event(number=number))
    )


def test_scoring_adapter_preserves_durable_context() -> None:
    event = make_event()

    scoring_input = MarketEventScoringAdapter().adapt(event)

    assert scoring_input.marketplace == event.marketplace
    assert scoring_input.external_id == event.external_id
    assert scoring_input.title == event.payload.title
    assert scoring_input.url == event.payload.url
    assert scoring_input.old_price == 1000.0
    assert scoring_input.new_price == 800.0
    assert scoring_input.currency == "RUB"
    assert scoring_input.discount_percentage == event.payload.percentage
    assert scoring_input.occurred_at == event.occurred_at
    assert scoring_input.detected_at == event.detected_at


def test_event_processing_configuration_has_safe_development_defaults() -> None:
    configuration = EventProcessingSettings.model_construct()

    assert configuration.scoring_batch_size == 50
    assert configuration.scoring_lease_seconds == 60
    assert configuration.scoring_maximum_attempts == 3
    assert configuration.scoring_initial_retry_seconds == 5
    assert configuration.scoring_maximum_retry_seconds == 300
    assert configuration.stale_claim_recovery_batch_size == 50
    assert configuration.stale_claim_recovery_interval_seconds == 30


def test_successful_scoring_uses_short_scopes_and_is_not_repeated() -> None:
    async def scenario() -> None:
        provider, tracker = make_tracked_provider()
        await add_event(provider)
        scorer = ScopeAssertingScorer(tracker)
        service = EventProcessingService(
            repository_scope_factory=tracker.factory(),
            scorer=scorer,
        )
        now = NOW + timedelta(minutes=10)

        first = await service.process_pending(worker_id="worker", limit=10, now=now)
        second = await service.process_pending(worker_id="worker", limit=10, now=now)
        stored = await provider.events.get_by_id(make_event().id)

        assert first.claimed == 1
        assert first.scored == 1
        assert first.items[0].score == 60
        assert first.items[0].scoring_status is ScoringStatus.SUCCEEDED
        assert second.claimed == 0
        assert scorer.calls == 1
        assert tracker.entries == 3
        assert tracker.active == 0
        assert stored is not None
        assert stored.score == 60
        assert stored.scoring_status is ScoringStatus.SUCCEEDED
        assert stored.claim is None

    run_async(scenario())


def test_active_lease_blocks_another_worker() -> None:
    async def scenario() -> None:
        provider, tracker = make_tracked_provider()
        await add_event(provider)
        now = NOW + timedelta(minutes=10)
        await provider.events.claim_pending(
            now,
            "first-worker",
            now + timedelta(minutes=1),
            1,
        )
        service = EventProcessingService(
            repository_scope_factory=tracker.factory(),
            scorer=EventScorer(),
        )

        result = await service.process_pending(
            worker_id="second-worker",
            limit=1,
            now=now + timedelta(seconds=30),
        )

        assert result.claimed == 0

    run_async(scenario())


def test_transient_failure_retries_without_persisting_exception_message() -> None:
    async def scenario() -> None:
        provider, tracker = make_tracked_provider()
        await add_event(provider)
        now = NOW + timedelta(minutes=10)
        failing = EventProcessingService(
            repository_scope_factory=tracker.factory(),
            scorer=RaisingScorer(RuntimeError("secret-token-value")),
        )

        failed = await failing.process_pending(worker_id="worker", limit=1, now=now)
        stored_failure = await provider.events.get_by_id(make_event().id)
        assert failed.retry_scheduled == 1
        assert failed.items[0].error_category is EventProcessingErrorCategory.TRANSIENT
        assert failed.items[0].next_retry_at == now + timedelta(seconds=5)
        assert stored_failure is not None
        assert stored_failure.last_error is not None
        assert "secret-token-value" not in stored_failure.last_error.summary

        succeeding = EventProcessingService(
            repository_scope_factory=tracker.factory(),
            scorer=EventScorer(),
        )
        retried = await succeeding.process_pending(
            worker_id="worker",
            limit=1,
            now=now + timedelta(seconds=5),
        )
        stored_success = await provider.events.get_by_id(make_event().id)

        assert retried.scored == 1
        assert stored_success is not None
        assert stored_success.scoring_attempt_count == 2
        assert stored_success.scoring_status is ScoringStatus.SUCCEEDED

    run_async(scenario())


def test_permanent_and_exhausted_failures_are_terminal() -> None:
    async def scenario() -> None:
        provider, tracker = make_tracked_provider()
        await add_event(provider, number=1)
        await add_event(provider, number=2)
        now = NOW + timedelta(minutes=10)
        permanent_service = EventProcessingService(
            repository_scope_factory=tracker.factory(),
            scorer=EventScorer(),
            adapter=PermanentlyFailingAdapter(),
        )
        permanent = await permanent_service.process_pending(
            worker_id="worker",
            limit=1,
            now=now,
        )
        exhausted_service = EventProcessingService(
            repository_scope_factory=tracker.factory(),
            scorer=RaisingScorer(RuntimeError("temporary")),
            retry_policy=ScoringRetryPolicy(maximum_attempts=1),
        )
        exhausted = await exhausted_service.process_pending(
            worker_id="worker",
            limit=1,
            now=now,
        )

        assert permanent.permanently_failed == 1
        assert (
            permanent.items[0].error_category
            is EventProcessingErrorCategory.PERMANENT_INPUT
        )
        assert exhausted.permanently_failed == 1
        assert (
            exhausted.items[0].error_category
            is EventProcessingErrorCategory.ATTEMPTS_EXHAUSTED
        )
        assert await provider.events.list_pending(now + timedelta(days=1), 10) == ()

    run_async(scenario())


def test_stale_claim_recovery_is_idempotent_and_invalidates_old_token() -> None:
    async def scenario() -> None:
        provider, tracker = make_tracked_provider()
        await add_event(provider)
        claimed_at = NOW + timedelta(minutes=10)
        lease_until = claimed_at + timedelta(minutes=1)
        old_claim = (
            await provider.events.claim_pending(
                claimed_at,
                "old-worker",
                lease_until,
                1,
            )
        )[0]
        service = EventProcessingService(
            repository_scope_factory=tracker.factory(),
            scorer=EventScorer(),
        )

        first = await service.recover_stale_scoring_claims(limit=10, now=lease_until)
        second = await service.recover_stale_scoring_claims(limit=10, now=lease_until)
        retry_at = lease_until + timedelta(seconds=5)
        new_claim = (
            await provider.events.claim_pending(
                retry_at,
                "new-worker",
                retry_at + timedelta(minutes=1),
                1,
            )
        )[0]
        stale_token = await provider.events.mark_scored(
            new_claim.event.id,
            old_claim.claim.token,
            new_claim.event.version,
            60,
            retry_at,
        )
        stale_version = await provider.events.mark_scored(
            new_claim.event.id,
            new_claim.claim.token,
            old_claim.event.version,
            60,
            retry_at,
        )

        assert first.expired_found == 1
        assert first.recovered == 1
        assert first.retry_scheduled == 1
        assert second.expired_found == 0
        assert stale_token.outcome is StateTransitionOutcome.CLAIM_LOST
        assert stale_version.outcome is StateTransitionOutcome.VERSION_CONFLICT

    run_async(scenario())


def test_batch_failure_does_not_corrupt_unrelated_event() -> None:
    async def scenario() -> None:
        provider, tracker = make_tracked_provider()
        await add_event(provider, number=1)
        await add_event(provider, number=2)
        service = EventProcessingService(
            repository_scope_factory=tracker.factory(),
            scorer=SelectiveScorer(),
        )

        result = await service.process_pending(
            worker_id="worker",
            limit=2,
            now=NOW + timedelta(minutes=10),
        )

        assert result.claimed == 2
        assert result.scored == 1
        assert result.retry_scheduled == 1
        assert result.processing_errors == 1

    run_async(scenario())


class RecordingProcessingService:
    """Record Scheduler job delegation without repositories or scoring."""

    def __init__(self) -> None:
        self.processing_calls: list[tuple[str, int, datetime]] = []
        self.recovery_calls: list[tuple[int, datetime]] = []

    async def process_pending(
        self,
        *,
        worker_id: str,
        limit: int,
        now: datetime,
    ) -> EventProcessingBatchResult:
        """Record one scoring job call."""
        self.processing_calls.append((worker_id, limit, now))
        return EventProcessingBatchResult(limit, 0, 0, 0, 0, 0, 0, ())

    async def recover_stale_scoring_claims(
        self,
        *,
        limit: int,
        now: datetime,
    ) -> StaleClaimRecoveryResult:
        """Record one recovery job call."""
        self.recovery_calls.append((limit, now))
        return StaleClaimRecoveryResult(limit, 0, 0, 0, 0, 0, 0, ())


def test_scheduler_jobs_only_delegate_to_event_processing_service() -> None:
    async def scenario() -> None:
        service = RecordingProcessingService()
        scoring_job = MarketEventScoringJob(
            service,
            worker_id="scheduler-worker",
            batch_size=25,
            clock=lambda: NOW,
        )
        recovery_job = StaleScoringClaimRecoveryJob(
            service,
            batch_size=15,
            clock=lambda: NOW + timedelta(minutes=1),
        )
        scheduler = SchedulerService()
        scheduler.register_job(scoring_job)
        scheduler.register_job(recovery_job)
        scheduler.start()

        await scheduler.execute_job(scoring_job.name)
        await scheduler.execute_job(recovery_job.name)
        await scheduler.stop()

        assert service.processing_calls == [("scheduler-worker", 25, NOW)]
        assert service.recovery_calls == [(15, NOW + timedelta(minutes=1))]
        assert (
            scheduler.get_status(scoring_job.name).state is JobExecutionState.SUCCEEDED
        )
        assert (
            scheduler.get_status(recovery_job.name).state is JobExecutionState.SUCCEEDED
        )
        assert scheduler.get_statistics(scoring_job.name).successful_executions == 1
        assert scheduler.get_statistics(recovery_job.name).successful_executions == 1

    run_async(scenario())
