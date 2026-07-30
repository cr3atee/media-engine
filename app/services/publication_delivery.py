from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from app.delivery.contracts import (
    DeliveryErrorCategory,
    DeliveryMessage,
    DeliveryOutcome,
    DeliveryResult,
    PublicationDeliveryAdapter,
)
from app.domain.generated_content import GeneratedContentAttempt
from app.domain.identity import normalize_utc
from app.domain.lifecycle import (
    ContentGenerationStatus,
    ContentReviewStatus,
    EventDisposition,
    PublicationStatus,
)
from app.domain.market_events import PriceDropMarketEvent
from app.domain.processing import (
    ProcessingError,
    StateTransitionOutcome,
    StateTransitionResult,
)
from app.domain.publications import ClaimedPublication, Publication
from app.services.repository_scope import RepositoryScopeFactory
from app.telegram.errors import TelegramFormattingError
from app.telegram.formatter import (
    TelegramFormattingRequest,
    TelegramPlainTextFormatter,
)
from app.telegram.security import (
    is_valid_telegram_destination,
    safe_destination_reference,
)

type Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PublicationDeliveryStatus(StrEnum):
    """Application-level delivery processing states."""

    PUBLISHED = "published"
    RETRY_SCHEDULED = "retry_scheduled"
    PERMANENT_FAILURE = "permanent_failure"
    AMBIGUOUS = "ambiguous"
    SKIPPED_NOT_ELIGIBLE = "skipped_not_eligible"
    SKIPPED_NOT_DUE = "skipped_not_due"
    CLAIM_LOST = "claim_lost"
    VERSION_CONFLICT = "version_conflict"
    INVALID_STATE = "invalid_state"
    RATE_LIMITED = "rate_limited"
    DRY_RUN = "dry_run"


class PublicationDeliveryErrorCategory(StrEnum):
    """Safe durable categories for publication-delivery service failures."""

    MISSING_PUBLICATION = "missing_publication"
    MISSING_CONTENT = "missing_content"
    MISSING_EVENT = "missing_event"
    UNSUPPORTED_CHANNEL = "unsupported_channel"
    INVALID_DESTINATION = "invalid_destination"
    DESTINATION_NOT_ALLOWED = "destination_not_allowed"
    INVALID_PUBLICATION_STATE = "invalid_publication_state"
    PUBLICATION_NOT_DUE = "publication_not_due"
    INVALID_CONTENT_STATE = "invalid_content_state"
    INVALID_REVIEW_STATE = "invalid_review_state"
    INVALID_EVENT_STATE = "invalid_event_state"
    EVENT_CONTENT_MISMATCH = "event_content_mismatch"
    FORMATTER_REJECTED = "formatter_rejected"
    ATTEMPTS_EXHAUSTED = "publication_attempts_exhausted"
    CLAIM_LOST = "claim_lost"
    VERSION_CONFLICT = "version_conflict"
    INVALID_STATE = "invalid_state"
    NOT_FOUND = "not_found"
    PERSISTENCE = "persistence_error"


@dataclass(slots=True, frozen=True)
class PublicationDeliveryRetryPolicy:
    """Deterministic retry policy applied after one adapter result."""

    maximum_attempts: int = 5
    initial_delay: timedelta = timedelta(seconds=30)
    maximum_delay: timedelta = timedelta(minutes=30)

    def __post_init__(self) -> None:
        if self.maximum_attempts < 1:
            msg = "Maximum publication-delivery attempts must be positive."
            raise ValueError(msg)
        if self.initial_delay <= timedelta(0):
            msg = "Initial publication-delivery retry delay must be positive."
            raise ValueError(msg)
        if self.maximum_delay < self.initial_delay:
            msg = "Maximum publication-delivery retry delay must not be below initial."
            raise ValueError(msg)

    def next_retry_at(
        self,
        now: datetime,
        attempt_number: int,
        provider_retry_after: timedelta | None = None,
    ) -> datetime | None:
        """Return the next durable retry time or ``None`` when exhausted."""
        now = normalize_utc(now, field_name="now")
        if attempt_number >= self.maximum_attempts:
            return None
        delay_seconds = self.initial_delay.total_seconds() * 2 ** max(
            attempt_number - 1,
            0,
        )
        delay = min(timedelta(seconds=delay_seconds), self.maximum_delay)
        if provider_retry_after is not None and provider_retry_after > delay:
            delay = provider_retry_after
        return now + delay


@dataclass(slots=True, frozen=True)
class PublicationDeliveryPolicy:
    """Configuration used by durable publication delivery orchestration."""

    channel: str = "telegram"
    lease_duration: timedelta = timedelta(seconds=60)
    retry_policy: PublicationDeliveryRetryPolicy = PublicationDeliveryRetryPolicy()
    allowed_destination_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        channel = self.channel.strip().lower()
        if not channel:
            msg = "Publication delivery channel must not be empty."
            raise ValueError(msg)
        if self.lease_duration <= timedelta(0):
            msg = "Publication delivery lease duration must be positive."
            raise ValueError(msg)
        object.__setattr__(self, "channel", channel)
        object.__setattr__(
            self,
            "allowed_destination_ids",
            frozenset(self.allowed_destination_ids),
        )


@dataclass(slots=True, frozen=True, kw_only=True)
class PublicationDeliveryItemResult:
    """Immutable safe result for one publication delivery attempt."""

    publication_id: UUID | None
    status: PublicationDeliveryStatus
    destination_reference: str | None
    attempt_number: int | None = None
    external_message_id: str | None = None
    next_retry_at: datetime | None = None
    error_category: str | None = None
    error_message: str | None = None
    dry_run_rendered_length: int | None = None
    stopped_after_rate_limit: bool = False
    adapter_outcome: DeliveryOutcome | None = None


@dataclass(slots=True, frozen=True)
class PublicationDeliveryBatchResult:
    """Immutable summary for one bounded delivery batch."""

    requested_limit: int
    claimed: int
    published: int
    retries_scheduled: int
    permanent_failures: int
    ambiguous: int
    dry_run: int
    skipped: int
    conflicts: int
    errors: int
    stopped_after_rate_limit: bool
    items: tuple[PublicationDeliveryItemResult, ...]


@dataclass(slots=True, frozen=True, kw_only=True)
class PublicationDryRunResult:
    """Read-only rendered publication preview and validation summary."""

    publication_id: UUID
    status: PublicationDeliveryStatus
    destination_reference: str | None
    rendered_text: str
    rendered_length: int
    validation_summary: tuple[str, ...]
    error_category: str | None = None
    error_message: str | None = None


@dataclass(slots=True, frozen=True)
class _PreparedPublication:
    publication: Publication
    content: GeneratedContentAttempt
    event: PriceDropMarketEvent
    message: DeliveryMessage


class _DeliveryPreparationError(ValueError):
    def __init__(
        self,
        category: PublicationDeliveryErrorCategory,
        summary: str,
        status: PublicationDeliveryStatus = PublicationDeliveryStatus.PERMANENT_FAILURE,
    ) -> None:
        self.category = category
        self.summary = summary
        self.status = status
        super().__init__(summary)


class PublicationDeliveryService:
    """Claim, render, send, and durably complete publication deliveries."""

    def __init__(
        self,
        *,
        repository_scope_factory: RepositoryScopeFactory,
        adapter: PublicationDeliveryAdapter,
        formatter: TelegramPlainTextFormatter | None = None,
        policy: PublicationDeliveryPolicy | None = None,
        clock: Clock = _utc_now,
    ) -> None:
        """Configure durable repositories, adapter, formatter, and retry policy."""
        self._repository_scope_factory = repository_scope_factory
        self._adapter = adapter
        self._formatter = formatter or TelegramPlainTextFormatter()
        self._policy = policy or PublicationDeliveryPolicy()
        self._clock = clock

    async def process_batch(
        self,
        *,
        worker_id: str,
        limit: int,
        now: datetime | None = None,
    ) -> PublicationDeliveryBatchResult:
        """Process one bounded Telegram publication batch sequentially."""
        now = normalize_utc(now or self._clock(), field_name="now")
        _validate_limit(limit)
        items: list[PublicationDeliveryItemResult] = []
        stopped_after_rate_limit = False

        for _ in range(limit):
            claimed = await self._claim_one(worker_id, now)
            if claimed is None:
                break
            item = await self._process_claimed(claimed, now)
            items.append(item)
            if item.stopped_after_rate_limit:
                stopped_after_rate_limit = True
                break

        return _batch_result(
            limit,
            tuple(items),
            stopped_after_rate_limit=stopped_after_rate_limit,
        )

    async def dry_run_publication(
        self,
        publication_id: UUID,
        *,
        now: datetime | None = None,
    ) -> PublicationDryRunResult:
        """Render and validate one publication without claims, sends, or writes."""
        now = normalize_utc(now or self._clock(), field_name="now")
        try:
            prepared = await self._prepare_publication(publication_id, now)
        except _DeliveryPreparationError as error:
            return PublicationDryRunResult(
                publication_id=publication_id,
                status=error.status,
                destination_reference=None,
                rendered_text="",
                rendered_length=0,
                validation_summary=(error.summary,),
                error_category=error.category.value,
                error_message=error.summary,
            )

        return PublicationDryRunResult(
            publication_id=publication_id,
            status=PublicationDeliveryStatus.DRY_RUN,
            destination_reference=safe_destination_reference(
                prepared.publication.destination_key
            ),
            rendered_text=prepared.message.rendered_text,
            rendered_length=len(prepared.message.rendered_text),
            validation_summary=("Publication can be rendered without mutation.",),
        )

    async def _claim_one(
        self,
        worker_id: str,
        now: datetime,
    ) -> ClaimedPublication | None:
        worker_id = worker_id.strip()
        if not worker_id:
            msg = "Publication delivery worker ID must not be empty."
            raise ValueError(msg)
        async with self._repository_scope_factory() as repositories:
            claimed = await repositories.publications.claim_pending(
                now,
                worker_id,
                now + self._policy.lease_duration,
                1,
                channel=self._policy.channel,
                maximum_attempts=self._policy.retry_policy.maximum_attempts,
            )
        return claimed[0] if claimed else None

    async def _process_claimed(
        self,
        claimed: ClaimedPublication,
        now: datetime,
    ) -> PublicationDeliveryItemResult:
        try:
            prepared = await self._prepare_publication(
                claimed.publication.id,
                now,
                allow_in_progress=True,
            )
        except _DeliveryPreparationError as error:
            return await self._complete_permanent_failure(
                claimed,
                error.category.value,
                error.summary,
                now,
            )

        delivery_result = await self._adapter.send(prepared.message)
        return await self._complete_adapter_result(claimed, delivery_result, now)

    async def _prepare_publication(
        self,
        publication_id: UUID,
        now: datetime,
        *,
        allow_in_progress: bool = False,
    ) -> _PreparedPublication:
        async with self._repository_scope_factory() as repositories:
            publication = await repositories.publications.get_by_id(publication_id)
            if publication is None:
                raise _DeliveryPreparationError(
                    PublicationDeliveryErrorCategory.MISSING_PUBLICATION,
                    "Publication was not found.",
                    PublicationDeliveryStatus.SKIPPED_NOT_ELIGIBLE,
                )

            content = await repositories.generated_contents.get_by_id(
                publication.content_id
            )
            if content is None:
                raise _DeliveryPreparationError(
                    PublicationDeliveryErrorCategory.MISSING_CONTENT,
                    "Generated content was not found.",
                )
            event = await repositories.events.get_by_id(publication.event_id)
            if event is None:
                raise _DeliveryPreparationError(
                    PublicationDeliveryErrorCategory.MISSING_EVENT,
                    "Market event was not found.",
                )

        self._validate(
            publication,
            content,
            event,
            now,
            allow_in_progress=allow_in_progress,
        )
        return _PreparedPublication(
            publication=publication,
            content=content,
            event=event,
            message=self._format_message(publication, content, event),
        )

    def _validate(
        self,
        publication: Publication,
        content: GeneratedContentAttempt,
        event: PriceDropMarketEvent,
        now: datetime,
        *,
        allow_in_progress: bool,
    ) -> None:
        if publication.channel != self._policy.channel:
            raise _DeliveryPreparationError(
                PublicationDeliveryErrorCategory.UNSUPPORTED_CHANNEL,
                "Publication channel is not supported by this delivery service.",
            )
        if publication.status in {
            PublicationStatus.PUBLISHED,
            PublicationStatus.CANCELLED,
            PublicationStatus.AMBIGUOUS,
        }:
            raise _DeliveryPreparationError(
                PublicationDeliveryErrorCategory.INVALID_PUBLICATION_STATE,
                "Publication is already terminal or requires manual resolution.",
                PublicationDeliveryStatus.SKIPPED_NOT_ELIGIBLE,
            )
        if (
            publication.status is PublicationStatus.IN_PROGRESS
            and not allow_in_progress
        ):
            raise _DeliveryPreparationError(
                PublicationDeliveryErrorCategory.INVALID_PUBLICATION_STATE,
                "Publication is actively claimed and cannot be dry-run as pending.",
                PublicationDeliveryStatus.SKIPPED_NOT_ELIGIBLE,
            )
        if publication.scheduled_at is not None and publication.scheduled_at > now:
            raise _DeliveryPreparationError(
                PublicationDeliveryErrorCategory.PUBLICATION_NOT_DUE,
                "Publication is not scheduled for delivery yet.",
                PublicationDeliveryStatus.SKIPPED_NOT_DUE,
            )
        if publication.status is PublicationStatus.FAILED:
            if publication.next_retry_at is None or publication.next_retry_at > now:
                raise _DeliveryPreparationError(
                    PublicationDeliveryErrorCategory.PUBLICATION_NOT_DUE,
                    "Publication retry is not due yet.",
                    PublicationDeliveryStatus.SKIPPED_NOT_DUE,
                )
        if not is_valid_telegram_destination(publication.destination_key):
            raise _DeliveryPreparationError(
                PublicationDeliveryErrorCategory.INVALID_DESTINATION,
                "Telegram destination must be a non-zero numeric chat ID.",
            )
        if (
            self._policy.allowed_destination_ids
            and publication.destination_key not in self._policy.allowed_destination_ids
        ):
            raise _DeliveryPreparationError(
                PublicationDeliveryErrorCategory.DESTINATION_NOT_ALLOWED,
                "Telegram destination is not in the delivery allowlist.",
            )
        if content.event_id != publication.event_id or event.id != publication.event_id:
            raise _DeliveryPreparationError(
                PublicationDeliveryErrorCategory.EVENT_CONTENT_MISMATCH,
                "Publication, content, and event identities do not match.",
            )
        if content.generation_status is not ContentGenerationStatus.GENERATED:
            raise _DeliveryPreparationError(
                PublicationDeliveryErrorCategory.INVALID_CONTENT_STATE,
                "Generated content is not in a successful state.",
            )
        if content.review_status not in {
            ContentReviewStatus.NOT_REQUIRED,
            ContentReviewStatus.APPROVED,
        }:
            raise _DeliveryPreparationError(
                PublicationDeliveryErrorCategory.INVALID_REVIEW_STATE,
                "Generated content is not approved for delivery.",
            )
        if event.disposition in {EventDisposition.IGNORED, EventDisposition.REJECTED}:
            raise _DeliveryPreparationError(
                PublicationDeliveryErrorCategory.INVALID_EVENT_STATE,
                "Market event is not eligible for publication.",
            )
        if content.content_text is None or not content.content_text.strip():
            raise _DeliveryPreparationError(
                PublicationDeliveryErrorCategory.INVALID_CONTENT_STATE,
                "Generated content text is empty.",
            )

    def _format_message(
        self,
        publication: Publication,
        content: GeneratedContentAttempt,
        event: PriceDropMarketEvent,
    ) -> DeliveryMessage:
        assert content.content_text is not None
        try:
            return self._formatter.format(
                TelegramFormattingRequest(
                    publication_id=publication.id,
                    channel=publication.channel,
                    destination_id=publication.destination_key,
                    generated_text=content.content_text,
                    source_url=event.payload.url,
                    footer=_event_footer(event),
                    correlation_id=publication.idempotency_key,
                    reference_id=content.id.hex,
                )
            )
        except TelegramFormattingError as error:
            raise _DeliveryPreparationError(
                PublicationDeliveryErrorCategory.FORMATTER_REJECTED,
                f"Telegram formatter rejected the publication ({error.code.value}).",
            ) from error

    async def _complete_adapter_result(
        self,
        claimed: ClaimedPublication,
        result: DeliveryResult,
        now: datetime,
    ) -> PublicationDeliveryItemResult:
        if result.outcome is DeliveryOutcome.SUCCESS:
            assert result.external_message_id is not None
            return await self._complete_success(claimed, result, now)
        if result.outcome is DeliveryOutcome.RETRYABLE_FAILURE:
            return await self._complete_retry(claimed, result, now)
        if result.outcome is DeliveryOutcome.AMBIGUOUS:
            return await self._complete_ambiguous(claimed, result, now)
        return await self._complete_permanent_failure(
            claimed,
            _error_category_value(result),
            result.error_message or "Telegram delivery was rejected permanently.",
            now,
            adapter_outcome=result.outcome,
        )

    async def _complete_success(
        self,
        claimed: ClaimedPublication,
        result: DeliveryResult,
        now: datetime,
    ) -> PublicationDeliveryItemResult:
        assert result.external_message_id is not None
        async with self._repository_scope_factory() as repositories:
            transition = await repositories.publications.mark_published(
                claimed.publication.id,
                claimed.claim.token,
                claimed.publication.version,
                result.external_message_id,
                now,
            )
        if transition.outcome is not StateTransitionOutcome.APPLIED:
            return _transition_item(claimed.publication, transition, result.outcome)
        return PublicationDeliveryItemResult(
            publication_id=claimed.publication.id,
            status=PublicationDeliveryStatus.PUBLISHED,
            destination_reference=safe_destination_reference(
                claimed.publication.destination_key
            ),
            attempt_number=claimed.publication.attempt_count,
            external_message_id=result.external_message_id,
            adapter_outcome=result.outcome,
        )

    async def _complete_retry(
        self,
        claimed: ClaimedPublication,
        result: DeliveryResult,
        now: datetime,
    ) -> PublicationDeliveryItemResult:
        next_retry_at = self._policy.retry_policy.next_retry_at(
            now,
            claimed.publication.attempt_count,
            result.retry_after,
        )
        async with self._repository_scope_factory() as repositories:
            transition = await repositories.publications.mark_failed(
                claimed.publication.id,
                claimed.claim.token,
                claimed.publication.version,
                _processing_error(_error_category_value(result), result),
                now,
                next_retry_at,
            )
        if transition.outcome is not StateTransitionOutcome.APPLIED:
            return _transition_item(claimed.publication, transition, result.outcome)
        stopped = result.error_category is DeliveryErrorCategory.RATE_LIMITED
        return PublicationDeliveryItemResult(
            publication_id=claimed.publication.id,
            status=(
                PublicationDeliveryStatus.RATE_LIMITED
                if stopped
                else PublicationDeliveryStatus.RETRY_SCHEDULED
            ),
            destination_reference=safe_destination_reference(
                claimed.publication.destination_key
            ),
            attempt_number=claimed.publication.attempt_count,
            next_retry_at=next_retry_at,
            error_category=_error_category_value(result),
            error_message=result.error_message,
            stopped_after_rate_limit=stopped,
            adapter_outcome=result.outcome,
        )

    async def _complete_permanent_failure(
        self,
        claimed: ClaimedPublication,
        error_category: str,
        error_message: str,
        now: datetime,
        adapter_outcome: DeliveryOutcome | None = None,
    ) -> PublicationDeliveryItemResult:
        async with self._repository_scope_factory() as repositories:
            transition = await repositories.publications.mark_failed(
                claimed.publication.id,
                claimed.claim.token,
                claimed.publication.version,
                ProcessingError(code=error_category, summary=error_message),
                now,
                None,
            )
        if transition.outcome is not StateTransitionOutcome.APPLIED:
            return _transition_item(claimed.publication, transition, adapter_outcome)
        return PublicationDeliveryItemResult(
            publication_id=claimed.publication.id,
            status=PublicationDeliveryStatus.PERMANENT_FAILURE,
            destination_reference=safe_destination_reference(
                claimed.publication.destination_key
            ),
            attempt_number=claimed.publication.attempt_count,
            error_category=error_category,
            error_message=error_message,
            adapter_outcome=adapter_outcome,
        )

    async def _complete_ambiguous(
        self,
        claimed: ClaimedPublication,
        result: DeliveryResult,
        now: datetime,
    ) -> PublicationDeliveryItemResult:
        async with self._repository_scope_factory() as repositories:
            transition = await repositories.publications.mark_ambiguous(
                claimed.publication.id,
                claimed.claim.token,
                claimed.publication.version,
                _processing_error(_error_category_value(result), result),
                now,
            )
        if transition.outcome is not StateTransitionOutcome.APPLIED:
            return _transition_item(claimed.publication, transition, result.outcome)
        return PublicationDeliveryItemResult(
            publication_id=claimed.publication.id,
            status=PublicationDeliveryStatus.AMBIGUOUS,
            destination_reference=safe_destination_reference(
                claimed.publication.destination_key
            ),
            attempt_number=claimed.publication.attempt_count,
            error_category=_error_category_value(result),
            error_message=result.error_message,
            adapter_outcome=result.outcome,
        )


def _event_footer(event: PriceDropMarketEvent) -> str:
    payload = event.payload
    title = payload.title or event.external_id
    return "\n".join(
        (
            f"Product: {title}",
            f"Marketplace: {event.marketplace}",
            (
                "Price: "
                f"{_format_decimal(payload.old_price)} {payload.currency} -> "
                f"{_format_decimal(payload.new_price)} {payload.currency}"
            ),
            f"Discount: {_format_decimal(payload.percentage)}%",
        )
    )


def _format_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _error_category_value(result: DeliveryResult) -> str:
    if result.error_category is None:
        return (
            PublicationDeliveryErrorCategory.PERSISTENCE.value
            if result.outcome is not DeliveryOutcome.SUCCESS
            else "delivery_success"
        )
    return result.error_category.value


def _processing_error(
    category: str,
    result: DeliveryResult,
) -> ProcessingError:
    summary = result.error_message or f"Delivery outcome: {result.outcome.value}."
    return ProcessingError(code=category, summary=summary)


def _transition_item(
    publication: Publication,
    transition: StateTransitionResult,
    adapter_outcome: DeliveryOutcome | None,
) -> PublicationDeliveryItemResult:
    return PublicationDeliveryItemResult(
        publication_id=publication.id,
        status=_transition_status(transition.outcome),
        destination_reference=safe_destination_reference(publication.destination_key),
        attempt_number=publication.attempt_count,
        error_category=_transition_error_category(transition.outcome).value,
        error_message=f"Publication transition failed: {transition.outcome.value}.",
        adapter_outcome=adapter_outcome,
    )


def _transition_status(outcome: StateTransitionOutcome) -> PublicationDeliveryStatus:
    if outcome is StateTransitionOutcome.CLAIM_LOST:
        return PublicationDeliveryStatus.CLAIM_LOST
    if outcome is StateTransitionOutcome.VERSION_CONFLICT:
        return PublicationDeliveryStatus.VERSION_CONFLICT
    return PublicationDeliveryStatus.INVALID_STATE


def _transition_error_category(
    outcome: StateTransitionOutcome,
) -> PublicationDeliveryErrorCategory:
    categories = {
        StateTransitionOutcome.CLAIM_LOST: PublicationDeliveryErrorCategory.CLAIM_LOST,
        StateTransitionOutcome.VERSION_CONFLICT: (
            PublicationDeliveryErrorCategory.VERSION_CONFLICT
        ),
        StateTransitionOutcome.INVALID_STATE: (
            PublicationDeliveryErrorCategory.INVALID_STATE
        ),
        StateTransitionOutcome.NOT_FOUND: PublicationDeliveryErrorCategory.NOT_FOUND,
    }
    return categories.get(outcome, PublicationDeliveryErrorCategory.PERSISTENCE)


def _batch_result(
    requested_limit: int,
    items: tuple[PublicationDeliveryItemResult, ...],
    *,
    stopped_after_rate_limit: bool,
) -> PublicationDeliveryBatchResult:
    return PublicationDeliveryBatchResult(
        requested_limit=requested_limit,
        claimed=len(items),
        published=sum(
            item.status is PublicationDeliveryStatus.PUBLISHED for item in items
        ),
        retries_scheduled=sum(
            item.status
            in {
                PublicationDeliveryStatus.RETRY_SCHEDULED,
                PublicationDeliveryStatus.RATE_LIMITED,
            }
            for item in items
        ),
        permanent_failures=sum(
            item.status is PublicationDeliveryStatus.PERMANENT_FAILURE for item in items
        ),
        ambiguous=sum(
            item.status is PublicationDeliveryStatus.AMBIGUOUS for item in items
        ),
        dry_run=sum(item.status is PublicationDeliveryStatus.DRY_RUN for item in items),
        skipped=sum(
            item.status
            in {
                PublicationDeliveryStatus.SKIPPED_NOT_DUE,
                PublicationDeliveryStatus.SKIPPED_NOT_ELIGIBLE,
            }
            for item in items
        ),
        conflicts=sum(
            item.status
            in {
                PublicationDeliveryStatus.CLAIM_LOST,
                PublicationDeliveryStatus.VERSION_CONFLICT,
            }
            for item in items
        ),
        errors=sum(item.error_category is not None for item in items),
        stopped_after_rate_limit=stopped_after_rate_limit,
        items=items,
    )


def _validate_limit(limit: int) -> None:
    if limit < 0:
        msg = "Publication delivery limit must not be negative."
        raise ValueError(msg)
