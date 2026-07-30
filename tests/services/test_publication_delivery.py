from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from app.delivery.contracts import (
    DeliveryErrorCategory,
    DeliveryMessage,
    DeliveryOutcome,
    DeliveryResult,
)
from app.domain.generated_content import (
    CreateContentAttempt,
    calculate_content_checksum,
)
from app.domain.lifecycle import ContentReviewStatus, PublicationStatus
from app.domain.market_events import MarketEventCandidate, PriceDropMarketEvent
from app.domain.publications import CreatePublication
from app.repositories.provider import RepositoryProvider, create_memory_provider
from app.scheduler import JobExecutionState, PendingPublicationDeliveryJob
from app.services.publication_delivery import (
    PublicationDeliveryPolicy,
    PublicationDeliveryRetryPolicy,
    PublicationDeliveryService,
    PublicationDeliveryStatus,
)
from app.services.repository_scope import RepositoryScopeFactory
from tests.repositories.contracts.factories import NOW, make_event, uuid_for

DESTINATION_ID = "-1001234567890"


def run_one[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run one async service scenario."""
    return asyncio.run(awaitable)


class ScopeTracker:
    """Expose whether adapter delivery runs inside a repository scope."""

    def __init__(self, provider: RepositoryProvider) -> None:
        self.provider = provider
        self.active = 0
        self.entries = 0

    def factory(self) -> RepositoryScopeFactory:
        """Return a tracked memory repository scope."""

        @asynccontextmanager
        async def scope() -> AsyncIterator[RepositoryProvider]:
            self.entries += 1
            self.active += 1
            try:
                yield self.provider
            finally:
                self.active -= 1

        return scope


class RecordingAdapter:
    """Return configured delivery results and record transaction boundaries."""

    def __init__(
        self,
        tracker: ScopeTracker,
        results: list[DeliveryResult],
    ) -> None:
        self._tracker = tracker
        self._results = results
        self.messages: list[DeliveryMessage] = []
        self.scope_states: list[int] = []

    async def send(self, message: DeliveryMessage) -> DeliveryResult:
        """Record one send attempt and return the next deterministic result."""
        self.messages.append(message)
        self.scope_states.append(self._tracker.active)
        return self._results[len(self.messages) - 1]


@dataclass(slots=True, frozen=True)
class SeededPublication:
    """Identifiers for one seeded delivery publication."""

    event: PriceDropMarketEvent
    content_id: UUID
    publication_id: UUID


async def _seed_publication(
    provider: RepositoryProvider,
    *,
    number: int = 1,
    destination_id: str = DESTINATION_ID,
    channel: str = "telegram",
    generated_text: str = "Generated publication text",
    approve: bool = True,
) -> SeededPublication:
    event = make_event(number=number, event_id=uuid_for(10_000 + number))
    await provider.events.add_idempotently(MarketEventCandidate(event=event))
    content_id = uuid_for(20_000 + number)
    command = CreateContentAttempt(
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
    await provider.generated_contents.create_attempt(command)
    claimed_content = (
        await provider.generated_contents.claim_pending(
            NOW + timedelta(minutes=10),
            "content-worker",
            NOW + timedelta(minutes=11),
            1,
        )
    )[0]
    await provider.generated_contents.complete_attempt(
        content_id,
        claimed_content.claim.token,
        claimed_content.content.version,
        generated_text,
        calculate_content_checksum(generated_text),
        NOW + timedelta(minutes=10, seconds=1),
    )
    if approve:
        completed = await provider.generated_contents.get_by_id(content_id)
        assert completed is not None
        await provider.generated_contents.set_review_status(
            content_id,
            ContentReviewStatus.APPROVED,
            NOW + timedelta(minutes=10, seconds=2),
            completed.version,
        )
    publication_id = uuid_for(30_000 + number)
    await provider.publications.create_idempotently(
        CreatePublication(
            id=publication_id,
            event_id=event.id,
            content_id=content_id,
            channel=channel,
            destination_key=destination_id,
            created_at=NOW + timedelta(minutes=11),
        )
    )
    return SeededPublication(event, content_id, publication_id)


def _service(
    tracker: ScopeTracker,
    adapter: RecordingAdapter,
    *,
    maximum_attempts: int = 5,
) -> PublicationDeliveryService:
    return PublicationDeliveryService(
        repository_scope_factory=tracker.factory(),
        adapter=adapter,
        policy=PublicationDeliveryPolicy(
            retry_policy=PublicationDeliveryRetryPolicy(
                maximum_attempts=maximum_attempts,
                initial_delay=timedelta(seconds=30),
                maximum_delay=timedelta(minutes=30),
            ),
            allowed_destination_ids=frozenset({DESTINATION_ID, "-1009876543210"}),
        ),
        clock=lambda: NOW + timedelta(minutes=20),
    )


async def _success_claims_sends_outside_scope_and_marks_published() -> None:
    provider = create_memory_provider()
    tracker = ScopeTracker(provider)
    seeded = await _seed_publication(provider)
    adapter = RecordingAdapter(
        tracker,
        [
            DeliveryResult(
                outcome=DeliveryOutcome.SUCCESS,
                destination_id=DESTINATION_ID,
                external_message_id="telegram-message-1",
            )
        ],
    )

    result = await _service(tracker, adapter).process_batch(
        worker_id="delivery-worker",
        limit=1,
    )
    stored = await provider.publications.get_by_id(seeded.publication_id)

    assert result.published == 1
    assert result.claimed == 1
    assert adapter.scope_states == [0]
    assert len(adapter.messages) == 1
    assert stored is not None
    assert stored.status is PublicationStatus.PUBLISHED
    assert stored.external_message_id == "telegram-message-1"


async def _rate_limit_schedules_retry_after_and_stops_batch() -> None:
    provider = create_memory_provider()
    tracker = ScopeTracker(provider)
    first = await _seed_publication(provider, number=1)
    second = await _seed_publication(
        provider,
        number=2,
        destination_id="-1009876543210",
    )
    adapter = RecordingAdapter(
        tracker,
        [
            DeliveryResult(
                outcome=DeliveryOutcome.RETRYABLE_FAILURE,
                destination_id=DESTINATION_ID,
                retry_after=timedelta(seconds=90),
                error_category=DeliveryErrorCategory.RATE_LIMITED,
                error_message="Telegram rate limit exceeded.",
            ),
            DeliveryResult(
                outcome=DeliveryOutcome.SUCCESS,
                destination_id="-1009876543210",
                external_message_id="should-not-send",
            ),
        ],
    )

    result = await _service(tracker, adapter).process_batch(
        worker_id="delivery-worker",
        limit=2,
    )
    stored_first = await provider.publications.get_by_id(first.publication_id)
    stored_second = await provider.publications.get_by_id(second.publication_id)

    assert result.retries_scheduled == 1
    assert result.stopped_after_rate_limit is True
    assert len(adapter.messages) == 1
    assert stored_first is not None
    assert stored_first.status is PublicationStatus.FAILED
    assert stored_first.next_retry_at == NOW + timedelta(minutes=21, seconds=30)
    assert stored_second is not None
    assert stored_second.status is PublicationStatus.PENDING


async def _unapproved_content_is_terminal_without_adapter_call() -> None:
    provider = create_memory_provider()
    tracker = ScopeTracker(provider)
    seeded = await _seed_publication(provider, approve=False)
    adapter = RecordingAdapter(tracker, [])

    result = await _service(tracker, adapter).process_batch(
        worker_id="delivery-worker",
        limit=1,
    )
    stored = await provider.publications.get_by_id(seeded.publication_id)

    assert result.permanent_failures == 1
    assert result.items[0].error_category == "invalid_review_state"
    assert adapter.messages == []
    assert stored is not None
    assert stored.status is PublicationStatus.FAILED
    assert stored.next_retry_at is None


async def _ambiguous_result_blocks_automatic_retry() -> None:
    provider = create_memory_provider()
    tracker = ScopeTracker(provider)
    seeded = await _seed_publication(provider)
    adapter = RecordingAdapter(
        tracker,
        [
            DeliveryResult(
                outcome=DeliveryOutcome.AMBIGUOUS,
                destination_id=DESTINATION_ID,
                error_category=DeliveryErrorCategory.READ_TIMEOUT,
                error_message="Telegram response timed out.",
            )
        ],
    )

    first = await _service(tracker, adapter).process_batch(
        worker_id="delivery-worker",
        limit=1,
    )
    second = await _service(tracker, adapter).process_batch(
        worker_id="delivery-worker",
        limit=1,
    )
    stored = await provider.publications.get_by_id(seeded.publication_id)

    assert first.ambiguous == 1
    assert second.claimed == 0
    assert stored is not None
    assert stored.status is PublicationStatus.AMBIGUOUS
    assert stored.next_retry_at is None


async def _dry_run_renders_without_mutation_or_adapter_call() -> None:
    provider = create_memory_provider()
    tracker = ScopeTracker(provider)
    seeded = await _seed_publication(provider)
    adapter = RecordingAdapter(tracker, [])
    service = _service(tracker, adapter)

    result = await service.dry_run_publication(seeded.publication_id)
    stored = await provider.publications.get_by_id(seeded.publication_id)
    source_url = seeded.event.payload.url
    assert source_url is not None

    assert result.status is PublicationDeliveryStatus.DRY_RUN
    assert "Generated publication text" in result.rendered_text
    assert source_url in result.rendered_text
    assert adapter.messages == []
    assert stored is not None
    assert stored.status is PublicationStatus.PENDING
    assert stored.attempt_count == 0
    assert stored.claim is None


async def _scheduler_delivery_job_only_delegates() -> None:
    class RecordingService:
        calls: list[tuple[str, int, datetime]]

        def __init__(self) -> None:
            self.calls = []

        async def process_batch(
            self,
            *,
            worker_id: str,
            limit: int,
            now: datetime,
        ) -> object:
            self.calls.append((worker_id, limit, now))
            return object()

    service = RecordingService()
    job = PendingPublicationDeliveryJob(
        service,
        worker_id="scheduler-delivery",
        batch_size=7,
        clock=lambda: NOW,
    )

    await job.execute()

    assert service.calls == [("scheduler-delivery", 7, NOW)]
    assert job.status.state is JobExecutionState.SUCCEEDED


def test_success_claims_sends_outside_scope_and_marks_published() -> None:
    run_one(_success_claims_sends_outside_scope_and_marks_published())


def test_rate_limit_schedules_retry_after_and_stops_batch() -> None:
    run_one(_rate_limit_schedules_retry_after_and_stops_batch())


def test_unapproved_content_is_terminal_without_adapter_call() -> None:
    run_one(_unapproved_content_is_terminal_without_adapter_call())


def test_ambiguous_result_blocks_automatic_retry() -> None:
    run_one(_ambiguous_result_blocks_automatic_retry())


def test_dry_run_renders_without_mutation_or_adapter_call() -> None:
    run_one(_dry_run_renders_without_mutation_or_adapter_call())


def test_scheduler_delivery_job_only_delegates() -> None:
    run_one(_scheduler_delivery_job_only_delegates())
