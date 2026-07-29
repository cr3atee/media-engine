from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from app.domain.generated_content import (
    ClaimedContentAttempt,
    CreateContentAttempt,
    GeneratedContentAttempt,
    calculate_content_checksum,
)
from app.domain.identity import normalize_utc
from app.domain.lifecycle import (
    ContentGenerationStatus,
    EventDisposition,
    ScoringStatus,
)
from app.domain.market_events import PriceDropMarketEvent
from app.domain.processing import (
    IdempotentCreateStatus,
    ProcessingError,
    StateTransitionOutcome,
    StateTransitionResult,
)
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.provider import RepositoryProvider
from app.services.content_generator import ContentGenerator
from app.services.content_processing_errors import PermanentContentProcessingError
from app.services.market_event_scoring_adapter import MarketEventScoringAdapter
from app.services.publication_intents import (
    PublicationIntentService,
    PublicationTarget,
)
from app.services.repository_scope import RepositoryScopeFactory

type ContentIdFactory = Callable[[], UUID]

_ELIGIBLE_DISPOSITIONS = frozenset({EventDisposition.ACTIVE, EventDisposition.APPROVED})


class ContentProcessingErrorCategory(StrEnum):
    """Safe result and persistence categories for content processing."""

    TRANSIENT = "transient_generation_error"
    PERMANENT_INPUT = "permanent_generation_input"
    ATTEMPTS_EXHAUSTED = "generation_attempts_exhausted"
    CLAIM_LOST = "claim_lost"
    VERSION_CONFLICT = "version_conflict"
    INVALID_STATE = "invalid_state"
    NOT_FOUND = "not_found"
    PERSISTENCE = "persistence_error"


@dataclass(slots=True, frozen=True)
class ContentRetryPolicy:
    """Bounded deterministic retry policy for immutable AI attempts."""

    maximum_attempts: int = 5
    initial_delay: timedelta = timedelta(seconds=30)
    maximum_delay: timedelta = timedelta(minutes=30)

    def __post_init__(self) -> None:
        if self.maximum_attempts < 1:
            msg = "Maximum content-generation attempts must be positive."
            raise ValueError(msg)
        if self.initial_delay <= timedelta(0):
            msg = "Initial content retry delay must be positive."
            raise ValueError(msg)
        if self.maximum_delay < self.initial_delay:
            msg = "Maximum content retry delay must not be below initial delay."
            raise ValueError(msg)

    def next_retry_at(
        self,
        now: datetime,
        attempt_number: int,
    ) -> datetime | None:
        """Return bounded exponential retry eligibility for a new attempt."""
        now = normalize_utc(now, field_name="now")
        if attempt_number >= self.maximum_attempts:
            return None
        seconds = self.initial_delay.total_seconds() * 2 ** max(
            attempt_number - 1,
            0,
        )
        return now + min(timedelta(seconds=seconds), self.maximum_delay)


@dataclass(slots=True, frozen=True)
class ContentGenerationDescriptor:
    """Non-secret immutable metadata recorded for each AI attempt."""

    content_type: str = "telegram_post"
    language: str = "ru"
    provider: str = "configured"
    model: str = "configured"
    prompt_version: str = "price_drop_v1"

    def __post_init__(self) -> None:
        for field_name in (
            "content_type",
            "language",
            "provider",
            "model",
            "prompt_version",
        ):
            value = getattr(self, field_name).strip()
            if not value:
                msg = f"Content generation {field_name} must not be empty."
                raise ValueError(msg)
            object.__setattr__(self, field_name, value)


@dataclass(slots=True, frozen=True)
class ContentProcessingItemResult:
    """Immutable durable result for one claimed generation attempt."""

    event_id: UUID
    content_id: UUID
    claimed: bool
    generated: bool
    attempt_number: int
    generation_status: ContentGenerationStatus
    next_retry_at: datetime | None
    publication_created: bool
    publication_existing: bool
    error_category: ContentProcessingErrorCategory | None
    transition_outcome: StateTransitionOutcome | None


@dataclass(slots=True, frozen=True)
class ContentProcessingBatchResult:
    """Immutable summary for one bounded content-generation batch."""

    requested_limit: int
    claimed: int
    generated: int
    retry_scheduled: int
    exhausted: int
    publications_created: int
    publications_existing: int
    conflicts: int
    errors: int
    items: tuple[ContentProcessingItemResult, ...]


@dataclass(slots=True, frozen=True)
class ContentClaimRecoveryResult:
    """Immutable summary for expired generation-claim recovery."""

    requested_limit: int
    expired_found: int
    abandoned: int
    conflicts: int


@dataclass(slots=True, frozen=True)
class _ClaimedGeneration:
    event: PriceDropMarketEvent
    attempt: ClaimedContentAttempt


class ContentGenerationProcessingService:
    """Prepare, claim, generate, and persist durable publication content."""

    def __init__(
        self,
        *,
        repository_scope_factory: RepositoryScopeFactory,
        content_generator: ContentGenerator,
        publication_intent_service: PublicationIntentService,
        descriptor: ContentGenerationDescriptor | None = None,
        retry_policy: ContentRetryPolicy | None = None,
        lease_duration: timedelta = timedelta(minutes=2),
        publication_target: PublicationTarget | None = None,
        adapter: MarketEventScoringAdapter | None = None,
        content_id_factory: ContentIdFactory = uuid4,
    ) -> None:
        """Configure durable repositories and the external generation boundary."""
        if lease_duration <= timedelta(0):
            msg = "Content-generation lease duration must be positive."
            raise ValueError(msg)
        self._repository_scope_factory = repository_scope_factory
        self._content_generator = content_generator
        self._publication_intent_service = publication_intent_service
        self._descriptor = descriptor or ContentGenerationDescriptor()
        self._retry_policy = retry_policy or ContentRetryPolicy()
        self._lease_duration = lease_duration
        self._publication_target = publication_target
        self._adapter = adapter or MarketEventScoringAdapter()
        self._content_id_factory = content_id_factory

    async def process_pending(
        self,
        *,
        worker_id: str,
        limit: int,
        now: datetime,
    ) -> ContentProcessingBatchResult:
        """Process one bounded batch with no transaction open during AI calls."""
        now = normalize_utc(now, field_name="now")
        _validate_limit(limit)
        claimed = await self._prepare_and_claim(worker_id, limit, now)
        items: list[ContentProcessingItemResult] = []

        for work in claimed:
            try:
                event_input = self._adapter.adapt(work.event)
                content_text = await self._content_generator.generate(event_input)
                content_checksum = calculate_content_checksum(content_text)
            except Exception as exc:
                items.append(await self._persist_failure(work.attempt, exc, now))
                continue
            items.append(
                await self._persist_success(
                    work.attempt,
                    content_text,
                    content_checksum,
                    now,
                )
            )

        return _batch_result(limit, tuple(items))

    async def recover_stale_generation_claims(
        self,
        *,
        limit: int,
        now: datetime,
    ) -> ContentClaimRecoveryResult:
        """Abandon expired attempts once so a new attempt can be prepared."""
        now = normalize_utc(now, field_name="now")
        _validate_limit(limit)
        abandoned = 0
        conflicts = 0
        async with self._repository_scope_factory() as repositories:
            expired = await repositories.generated_contents.list_expired_claims(
                now,
                limit,
            )
            for claimed in expired:
                transition = await repositories.generated_contents.release_claim(
                    claimed.content.id,
                    claimed.claim.token,
                    claimed.content.version,
                    now,
                )
                if transition.outcome is StateTransitionOutcome.APPLIED:
                    abandoned += 1
                else:
                    conflicts += 1
        return ContentClaimRecoveryResult(
            requested_limit=limit,
            expired_found=len(expired),
            abandoned=abandoned,
            conflicts=conflicts,
        )

    async def _prepare_and_claim(
        self,
        worker_id: str,
        limit: int,
        now: datetime,
    ) -> tuple[_ClaimedGeneration, ...]:
        if limit == 0:
            return ()
        async with self._repository_scope_factory() as repositories:
            claims = list(
                await repositories.generated_contents.claim_pending(
                    now,
                    worker_id,
                    now + self._lease_duration,
                    limit,
                )
            )
            remaining = limit - len(claims)
            offset = 0
            page_size = max(limit, 25)
            while remaining > 0:
                events = await repositories.events.list_content_eligible(
                    page_size,
                    offset,
                )
                if not events:
                    break
                for event in events:
                    created = await self._prepare_attempt(repositories, event, now)
                    if created:
                        remaining -= 1
                        if remaining == 0:
                            break
                offset += len(events)
                if len(events) < page_size:
                    break

            if len(claims) < limit:
                claims.extend(
                    await repositories.generated_contents.claim_pending(
                        now,
                        worker_id,
                        now + self._lease_duration,
                        limit - len(claims),
                    )
                )

            work: list[_ClaimedGeneration] = []
            for attempt in claims:
                claimed_event = await repositories.events.get_by_id(
                    attempt.content.event_id
                )
                if claimed_event is None or not _event_is_eligible(claimed_event):
                    await repositories.generated_contents.release_claim(
                        attempt.content.id,
                        attempt.claim.token,
                        attempt.content.version,
                        now,
                    )
                    continue
                work.append(_ClaimedGeneration(event=claimed_event, attempt=attempt))
            return tuple(work)

    async def _prepare_attempt(
        self,
        repositories: RepositoryProvider,
        event: PriceDropMarketEvent,
        now: datetime,
    ) -> bool:
        latest = await repositories.generated_contents.get_latest_revision(
            event.id,
            self._descriptor.content_type,
            self._descriptor.language,
        )
        attempt_number = _next_attempt_number(
            latest,
            now,
            self._retry_policy.maximum_attempts,
        )
        if attempt_number is None:
            return False
        command = CreateContentAttempt(
            id=self._content_id_factory(),
            event_id=event.id,
            content_type=self._descriptor.content_type,
            language=self._descriptor.language,
            prompt_version=self._descriptor.prompt_version,
            attempt_number=attempt_number,
            provider=self._descriptor.provider,
            model=self._descriptor.model,
            created_at=now,
        )
        try:
            result = await repositories.generated_contents.create_attempt(command)
        except RepositoryIdentityConflictError:
            return False
        return result.status is IdempotentCreateStatus.CREATED

    async def _persist_success(
        self,
        claimed: ClaimedContentAttempt,
        content_text: str,
        content_checksum: str,
        completed_at: datetime,
    ) -> ContentProcessingItemResult:
        try:
            async with self._repository_scope_factory() as repositories:
                transition = await repositories.generated_contents.complete_attempt(
                    claimed.content.id,
                    claimed.claim.token,
                    claimed.content.version,
                    content_text,
                    content_checksum,
                    completed_at,
                )
                if transition.outcome is not StateTransitionOutcome.APPLIED:
                    return _transition_failure_item(claimed, transition)

                publication_created = False
                publication_existing = False
                if self._publication_target is not None:
                    publication = await self._publication_intent_service.create(
                        repositories.publications,
                        event_id=claimed.content.event_id,
                        content_id=claimed.content.id,
                        target=self._publication_target,
                        created_at=completed_at,
                    )
                    publication_created = publication.created
                    publication_existing = not publication.created
        except Exception:
            return _persistence_error_item(claimed)

        return ContentProcessingItemResult(
            event_id=claimed.content.event_id,
            content_id=claimed.content.id,
            claimed=True,
            generated=True,
            attempt_number=claimed.content.attempt_number,
            generation_status=ContentGenerationStatus.GENERATED,
            next_retry_at=None,
            publication_created=publication_created,
            publication_existing=publication_existing,
            error_category=None,
            transition_outcome=StateTransitionOutcome.APPLIED,
        )

    async def _persist_failure(
        self,
        claimed: ClaimedContentAttempt,
        exc: Exception,
        failed_at: datetime,
    ) -> ContentProcessingItemResult:
        category, retry_at = self._classify_failure(claimed, exc, failed_at)
        try:
            async with self._repository_scope_factory() as repositories:
                transition = await repositories.generated_contents.fail_attempt(
                    claimed.content.id,
                    claimed.claim.token,
                    claimed.content.version,
                    _processing_error(category, exc),
                    failed_at,
                    retry_at,
                )
        except Exception:
            return _persistence_error_item(claimed)
        if transition.outcome is not StateTransitionOutcome.APPLIED:
            return _transition_failure_item(claimed, transition)
        return ContentProcessingItemResult(
            event_id=claimed.content.event_id,
            content_id=claimed.content.id,
            claimed=True,
            generated=False,
            attempt_number=claimed.content.attempt_number,
            generation_status=ContentGenerationStatus.FAILED,
            next_retry_at=retry_at,
            publication_created=False,
            publication_existing=False,
            error_category=category,
            transition_outcome=transition.outcome,
        )

    def _classify_failure(
        self,
        claimed: ClaimedContentAttempt,
        exc: Exception,
        now: datetime,
    ) -> tuple[ContentProcessingErrorCategory, datetime | None]:
        if isinstance(exc, (PermanentContentProcessingError, TypeError, ValueError)):
            return ContentProcessingErrorCategory.PERMANENT_INPUT, None
        retry_at = self._retry_policy.next_retry_at(
            now,
            claimed.content.attempt_number,
        )
        if retry_at is None:
            return ContentProcessingErrorCategory.ATTEMPTS_EXHAUSTED, None
        return ContentProcessingErrorCategory.TRANSIENT, retry_at


def _event_is_eligible(event: PriceDropMarketEvent) -> bool:
    return (
        event.disposition in _ELIGIBLE_DISPOSITIONS
        and event.scoring_status is ScoringStatus.SUCCEEDED
        and event.score is not None
    )


def _next_attempt_number(
    latest: GeneratedContentAttempt | None,
    now: datetime,
    maximum_attempts: int,
) -> int | None:
    if latest is None:
        return 1
    if latest.attempt_number >= maximum_attempts:
        return None
    if latest.generation_status is ContentGenerationStatus.ABANDONED:
        return latest.attempt_number + 1
    if latest.generation_status is ContentGenerationStatus.FAILED:
        if latest.next_retry_at is not None and latest.next_retry_at <= now:
            return latest.attempt_number + 1
    return None


def _batch_result(
    requested_limit: int,
    items: tuple[ContentProcessingItemResult, ...],
) -> ContentProcessingBatchResult:
    return ContentProcessingBatchResult(
        requested_limit=requested_limit,
        claimed=len(items),
        generated=sum(item.generated for item in items),
        retry_scheduled=sum(item.next_retry_at is not None for item in items),
        exhausted=sum(
            item.error_category is ContentProcessingErrorCategory.ATTEMPTS_EXHAUSTED
            for item in items
        ),
        publications_created=sum(item.publication_created for item in items),
        publications_existing=sum(item.publication_existing for item in items),
        conflicts=sum(
            item.error_category
            in {
                ContentProcessingErrorCategory.CLAIM_LOST,
                ContentProcessingErrorCategory.VERSION_CONFLICT,
            }
            for item in items
        ),
        errors=sum(item.error_category is not None for item in items),
        items=items,
    )


def _transition_failure_item(
    claimed: ClaimedContentAttempt,
    transition: StateTransitionResult,
) -> ContentProcessingItemResult:
    return ContentProcessingItemResult(
        event_id=claimed.content.event_id,
        content_id=claimed.content.id,
        claimed=True,
        generated=False,
        attempt_number=claimed.content.attempt_number,
        generation_status=ContentGenerationStatus.IN_PROGRESS,
        next_retry_at=None,
        publication_created=False,
        publication_existing=False,
        error_category=_transition_category(transition.outcome),
        transition_outcome=transition.outcome,
    )


def _persistence_error_item(
    claimed: ClaimedContentAttempt,
) -> ContentProcessingItemResult:
    return ContentProcessingItemResult(
        event_id=claimed.content.event_id,
        content_id=claimed.content.id,
        claimed=True,
        generated=False,
        attempt_number=claimed.content.attempt_number,
        generation_status=ContentGenerationStatus.IN_PROGRESS,
        next_retry_at=None,
        publication_created=False,
        publication_existing=False,
        error_category=ContentProcessingErrorCategory.PERSISTENCE,
        transition_outcome=None,
    )


def _transition_category(
    outcome: StateTransitionOutcome,
) -> ContentProcessingErrorCategory:
    categories = {
        StateTransitionOutcome.CLAIM_LOST: ContentProcessingErrorCategory.CLAIM_LOST,
        StateTransitionOutcome.VERSION_CONFLICT: (
            ContentProcessingErrorCategory.VERSION_CONFLICT
        ),
        StateTransitionOutcome.INVALID_STATE: (
            ContentProcessingErrorCategory.INVALID_STATE
        ),
        StateTransitionOutcome.NOT_FOUND: ContentProcessingErrorCategory.NOT_FOUND,
    }
    return categories.get(outcome, ContentProcessingErrorCategory.PERSISTENCE)


def _processing_error(
    category: ContentProcessingErrorCategory,
    exc: Exception,
) -> ProcessingError:
    return ProcessingError(
        code=category.value,
        summary=f"Content generation failed ({type(exc).__name__}).",
    )


def _validate_limit(limit: int) -> None:
    if limit < 0:
        msg = "Content processing limit must not be negative."
        raise ValueError(msg)
