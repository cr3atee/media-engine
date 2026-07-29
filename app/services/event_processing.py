from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from app.domain.identity import normalize_utc
from app.domain.lifecycle import ScoringStatus
from app.domain.market_events import ClaimedMarketEvent
from app.domain.processing import (
    ProcessingError,
    StateTransitionOutcome,
    StateTransitionResult,
)
from app.insights.scoring import EventScorer
from app.services.event_processing_errors import PermanentEventProcessingError
from app.services.market_event_scoring_adapter import MarketEventScoringAdapter
from app.services.repository_scope import RepositoryScopeFactory


class EventProcessingErrorCategory(StrEnum):
    """Safe application-level categories for durable scoring outcomes."""

    TRANSIENT = "transient_scoring_error"
    PERMANENT_INPUT = "permanent_input"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"
    STALE_CLAIM_RECOVERED = "stale_claim_recovered"
    STALE_CLAIM_EXHAUSTED = "stale_claim_exhausted"
    CLAIM_LOST = "claim_lost"
    VERSION_CONFLICT = "version_conflict"
    INVALID_STATE = "invalid_state"
    NOT_FOUND = "not_found"
    PERSISTENCE = "persistence_error"


@dataclass(slots=True, frozen=True)
class ScoringRetryPolicy:
    """Bounded deterministic retry policy for durable event scoring."""

    maximum_attempts: int = 3
    initial_delay: timedelta = timedelta(seconds=5)
    maximum_delay: timedelta = timedelta(minutes=5)

    def __post_init__(self) -> None:
        if self.maximum_attempts < 1:
            msg = "Maximum scoring attempts must be positive."
            raise ValueError(msg)
        if self.initial_delay <= timedelta(0):
            msg = "Initial scoring retry delay must be positive."
            raise ValueError(msg)
        if self.maximum_delay < self.initial_delay:
            msg = "Maximum scoring retry delay must not be below the initial delay."
            raise ValueError(msg)

    def next_retry_at(
        self,
        now: datetime,
        attempt_number: int,
    ) -> datetime | None:
        """Return exponential retry eligibility or terminal exhaustion."""
        now = normalize_utc(now, field_name="now")
        if attempt_number >= self.maximum_attempts:
            return None
        delay_seconds = self.initial_delay.total_seconds() * 2 ** max(
            attempt_number - 1,
            0,
        )
        delay = min(
            timedelta(seconds=delay_seconds),
            self.maximum_delay,
        )
        return now + delay


@dataclass(slots=True, frozen=True)
class EventProcessingItemResult:
    """Durable scoring outcome for one claimed market event."""

    event_id: UUID
    claimed: bool
    score: int | None
    scoring_status: ScoringStatus
    attempt_number: int
    next_retry_at: datetime | None
    error_category: EventProcessingErrorCategory | None
    transition_outcome: StateTransitionOutcome | None


@dataclass(slots=True, frozen=True)
class EventProcessingBatchResult:
    """Immutable summary of one bounded event-scoring batch."""

    requested_limit: int
    claimed: int
    scored: int
    retry_scheduled: int
    permanently_failed: int
    claim_conflicts: int
    processing_errors: int
    items: tuple[EventProcessingItemResult, ...]


@dataclass(slots=True, frozen=True)
class StaleClaimRecoveryResult:
    """Immutable summary of one bounded stale-claim recovery run."""

    requested_limit: int
    expired_found: int
    recovered: int
    retry_scheduled: int
    permanently_failed: int
    claim_conflicts: int
    processing_errors: int
    items: tuple[EventProcessingItemResult, ...]


class EventProcessingService:
    """Claim, score, and durably complete market events in short transactions."""

    def __init__(
        self,
        *,
        repository_scope_factory: RepositoryScopeFactory,
        scorer: EventScorer,
        retry_policy: ScoringRetryPolicy | None = None,
        lease_duration: timedelta = timedelta(minutes=1),
        adapter: MarketEventScoringAdapter | None = None,
    ) -> None:
        """Configure repository scopes and deterministic scoring policy."""
        if lease_duration <= timedelta(0):
            msg = "Scoring lease duration must be positive."
            raise ValueError(msg)
        self._repository_scope_factory = repository_scope_factory
        self._scorer = scorer
        self._retry_policy = retry_policy or ScoringRetryPolicy()
        self._lease_duration = lease_duration
        self._adapter = adapter or MarketEventScoringAdapter()

    async def process_pending(
        self,
        *,
        worker_id: str,
        limit: int,
        now: datetime,
    ) -> EventProcessingBatchResult:
        """Process one bounded batch without holding a transaction while scoring."""
        now = normalize_utc(now, field_name="now")
        _validate_limit(limit)
        claimed = await self._claim_pending(worker_id, limit, now)
        items: list[EventProcessingItemResult] = []

        for claimed_event in claimed:
            try:
                scoring_input = self._adapter.adapt(claimed_event.event)
                score = self._scorer.score(scoring_input)
            except Exception as exc:
                items.append(
                    await self._persist_scoring_failure(claimed_event, exc, now)
                )
                continue

            items.append(await self._persist_score(claimed_event, score, now))

        return _batch_result(limit, tuple(items))

    async def recover_stale_scoring_claims(
        self,
        *,
        limit: int,
        now: datetime,
    ) -> StaleClaimRecoveryResult:
        """Recover expired claims once according to the persisted attempt budget."""
        now = normalize_utc(now, field_name="now")
        _validate_limit(limit)
        items: list[EventProcessingItemResult] = []

        async with self._repository_scope_factory() as repositories:
            expired = await repositories.events.list_expired_scoring_claims(
                now,
                limit,
            )
            for claimed_event in expired:
                retry_at = self._retry_policy.next_retry_at(
                    now,
                    claimed_event.event.scoring_attempt_count,
                )
                category = (
                    EventProcessingErrorCategory.STALE_CLAIM_RECOVERED
                    if retry_at is not None
                    else EventProcessingErrorCategory.STALE_CLAIM_EXHAUSTED
                )
                transition = await repositories.events.mark_scoring_failed(
                    claimed_event.event.id,
                    claimed_event.claim.token,
                    claimed_event.event.version,
                    _processing_error(category, RuntimeError()),
                    now,
                    retry_at,
                )
                items.append(
                    _failure_item(
                        claimed_event,
                        category,
                        retry_at,
                        transition,
                    )
                )

        item_tuple = tuple(items)
        return StaleClaimRecoveryResult(
            requested_limit=limit,
            expired_found=len(item_tuple),
            recovered=sum(
                item.transition_outcome is StateTransitionOutcome.APPLIED
                for item in item_tuple
            ),
            retry_scheduled=sum(item.next_retry_at is not None for item in item_tuple),
            permanently_failed=sum(
                item.scoring_status is ScoringStatus.FAILED
                and item.next_retry_at is None
                and item.transition_outcome is StateTransitionOutcome.APPLIED
                for item in item_tuple
            ),
            claim_conflicts=sum(_is_claim_conflict(item) for item in item_tuple),
            processing_errors=sum(
                item.error_category is not None for item in item_tuple
            ),
            items=item_tuple,
        )

    async def _claim_pending(
        self,
        worker_id: str,
        limit: int,
        now: datetime,
    ) -> tuple[ClaimedMarketEvent, ...]:
        async with self._repository_scope_factory() as repositories:
            claimed = await repositories.events.claim_pending(
                now,
                worker_id,
                now + self._lease_duration,
                limit,
            )
        return tuple(claimed)

    async def _persist_score(
        self,
        claimed_event: ClaimedMarketEvent,
        score: int,
        completed_at: datetime,
    ) -> EventProcessingItemResult:
        try:
            async with self._repository_scope_factory() as repositories:
                transition = await repositories.events.mark_scored(
                    claimed_event.event.id,
                    claimed_event.claim.token,
                    claimed_event.event.version,
                    score,
                    completed_at,
                )
        except Exception:
            return _persistence_error_item(claimed_event)

        if transition.outcome is StateTransitionOutcome.APPLIED:
            return EventProcessingItemResult(
                event_id=claimed_event.event.id,
                claimed=True,
                score=score,
                scoring_status=ScoringStatus.SUCCEEDED,
                attempt_number=claimed_event.event.scoring_attempt_count,
                next_retry_at=None,
                error_category=None,
                transition_outcome=transition.outcome,
            )
        return _transition_failure_item(claimed_event, transition)

    async def _persist_scoring_failure(
        self,
        claimed_event: ClaimedMarketEvent,
        exc: Exception,
        failed_at: datetime,
    ) -> EventProcessingItemResult:
        category, retry_at = self._classify_failure(claimed_event, exc, failed_at)
        try:
            async with self._repository_scope_factory() as repositories:
                transition = await repositories.events.mark_scoring_failed(
                    claimed_event.event.id,
                    claimed_event.claim.token,
                    claimed_event.event.version,
                    _processing_error(category, exc),
                    failed_at,
                    retry_at,
                )
        except Exception:
            return _persistence_error_item(claimed_event)

        return _failure_item(claimed_event, category, retry_at, transition)

    def _classify_failure(
        self,
        claimed_event: ClaimedMarketEvent,
        exc: Exception,
        now: datetime,
    ) -> tuple[EventProcessingErrorCategory, datetime | None]:
        if isinstance(exc, (PermanentEventProcessingError, TypeError, ValueError)):
            return EventProcessingErrorCategory.PERMANENT_INPUT, None
        retry_at = self._retry_policy.next_retry_at(
            now,
            claimed_event.event.scoring_attempt_count,
        )
        if retry_at is None:
            return EventProcessingErrorCategory.ATTEMPTS_EXHAUSTED, None
        return EventProcessingErrorCategory.TRANSIENT, retry_at


def _batch_result(
    requested_limit: int,
    items: tuple[EventProcessingItemResult, ...],
) -> EventProcessingBatchResult:
    return EventProcessingBatchResult(
        requested_limit=requested_limit,
        claimed=len(items),
        scored=sum(item.scoring_status is ScoringStatus.SUCCEEDED for item in items),
        retry_scheduled=sum(item.next_retry_at is not None for item in items),
        permanently_failed=sum(
            item.scoring_status is ScoringStatus.FAILED
            and item.next_retry_at is None
            and item.transition_outcome is StateTransitionOutcome.APPLIED
            for item in items
        ),
        claim_conflicts=sum(_is_claim_conflict(item) for item in items),
        processing_errors=sum(item.error_category is not None for item in items),
        items=items,
    )


def _failure_item(
    claimed_event: ClaimedMarketEvent,
    category: EventProcessingErrorCategory,
    retry_at: datetime | None,
    transition: StateTransitionResult,
) -> EventProcessingItemResult:
    if transition.outcome is not StateTransitionOutcome.APPLIED:
        return _transition_failure_item(claimed_event, transition)
    return EventProcessingItemResult(
        event_id=claimed_event.event.id,
        claimed=True,
        score=None,
        scoring_status=ScoringStatus.FAILED,
        attempt_number=claimed_event.event.scoring_attempt_count,
        next_retry_at=retry_at,
        error_category=category,
        transition_outcome=transition.outcome,
    )


def _transition_failure_item(
    claimed_event: ClaimedMarketEvent,
    transition: StateTransitionResult,
) -> EventProcessingItemResult:
    return EventProcessingItemResult(
        event_id=claimed_event.event.id,
        claimed=True,
        score=None,
        scoring_status=ScoringStatus.IN_PROGRESS,
        attempt_number=claimed_event.event.scoring_attempt_count,
        next_retry_at=None,
        error_category=_transition_category(transition.outcome),
        transition_outcome=transition.outcome,
    )


def _persistence_error_item(
    claimed_event: ClaimedMarketEvent,
) -> EventProcessingItemResult:
    return EventProcessingItemResult(
        event_id=claimed_event.event.id,
        claimed=True,
        score=None,
        scoring_status=ScoringStatus.IN_PROGRESS,
        attempt_number=claimed_event.event.scoring_attempt_count,
        next_retry_at=None,
        error_category=EventProcessingErrorCategory.PERSISTENCE,
        transition_outcome=None,
    )


def _transition_category(
    outcome: StateTransitionOutcome,
) -> EventProcessingErrorCategory:
    categories = {
        StateTransitionOutcome.CLAIM_LOST: EventProcessingErrorCategory.CLAIM_LOST,
        StateTransitionOutcome.VERSION_CONFLICT: (
            EventProcessingErrorCategory.VERSION_CONFLICT
        ),
        StateTransitionOutcome.INVALID_STATE: (
            EventProcessingErrorCategory.INVALID_STATE
        ),
        StateTransitionOutcome.NOT_FOUND: EventProcessingErrorCategory.NOT_FOUND,
    }
    return categories.get(outcome, EventProcessingErrorCategory.PERSISTENCE)


def _is_claim_conflict(item: EventProcessingItemResult) -> bool:
    return item.error_category in {
        EventProcessingErrorCategory.CLAIM_LOST,
        EventProcessingErrorCategory.VERSION_CONFLICT,
    }


def _processing_error(
    category: EventProcessingErrorCategory,
    exc: Exception,
) -> ProcessingError:
    exception_name = type(exc).__name__
    return ProcessingError(
        code=category.value,
        summary=f"Scoring processing failed ({exception_name}).",
    )


def _validate_limit(limit: int) -> None:
    if limit < 0:
        msg = "Event processing limit must not be negative."
        raise ValueError(msg)
