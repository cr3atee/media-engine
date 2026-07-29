from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum


class InvalidLifecycleTransition(ValueError):
    """Raised when a lifecycle state change is not permitted."""


class EventDisposition(StrEnum):
    """Administrative disposition of a persistent market event."""

    ACTIVE = "active"
    REVIEW_PENDING = "review_pending"
    APPROVED = "approved"
    IGNORED = "ignored"
    REJECTED = "rejected"


class ScoringStatus(StrEnum):
    """Persistent scoring work state for a market event."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class ContentGenerationStatus(StrEnum):
    """Lifecycle state of one immutable content-generation attempt."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    GENERATED = "generated"
    FAILED = "failed"
    ABANDONED = "abandoned"


class ContentReviewStatus(StrEnum):
    """Administrative review state of one content revision."""

    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class PublicationStatus(StrEnum):
    """Channel-independent delivery lifecycle state."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PUBLISHED = "published"
    FAILED = "failed"
    AMBIGUOUS = "ambiguous"
    CANCELLED = "cancelled"


_EVENT_DISPOSITION_TRANSITIONS: Mapping[
    EventDisposition,
    frozenset[EventDisposition],
] = {
    EventDisposition.ACTIVE: frozenset(
        {
            EventDisposition.REVIEW_PENDING,
            EventDisposition.APPROVED,
            EventDisposition.IGNORED,
            EventDisposition.REJECTED,
        },
    ),
    EventDisposition.REVIEW_PENDING: frozenset(
        {
            EventDisposition.APPROVED,
            EventDisposition.IGNORED,
            EventDisposition.REJECTED,
        },
    ),
    EventDisposition.APPROVED: frozenset(
        {EventDisposition.IGNORED, EventDisposition.REJECTED},
    ),
    EventDisposition.IGNORED: frozenset(),
    EventDisposition.REJECTED: frozenset(),
}

_SCORING_STATUS_TRANSITIONS: Mapping[ScoringStatus, frozenset[ScoringStatus]] = {
    ScoringStatus.PENDING: frozenset(
        {ScoringStatus.IN_PROGRESS, ScoringStatus.SKIPPED},
    ),
    ScoringStatus.IN_PROGRESS: frozenset(
        {ScoringStatus.SUCCEEDED, ScoringStatus.FAILED},
    ),
    ScoringStatus.SUCCEEDED: frozenset(),
    ScoringStatus.FAILED: frozenset({ScoringStatus.PENDING}),
    ScoringStatus.SKIPPED: frozenset(),
}

_CONTENT_GENERATION_TRANSITIONS: Mapping[
    ContentGenerationStatus,
    frozenset[ContentGenerationStatus],
] = {
    ContentGenerationStatus.PENDING: frozenset(
        {ContentGenerationStatus.IN_PROGRESS, ContentGenerationStatus.ABANDONED},
    ),
    ContentGenerationStatus.IN_PROGRESS: frozenset(
        {
            ContentGenerationStatus.GENERATED,
            ContentGenerationStatus.FAILED,
            ContentGenerationStatus.ABANDONED,
        },
    ),
    ContentGenerationStatus.GENERATED: frozenset(),
    ContentGenerationStatus.FAILED: frozenset(),
    ContentGenerationStatus.ABANDONED: frozenset(),
}

_CONTENT_REVIEW_TRANSITIONS: Mapping[
    ContentReviewStatus,
    frozenset[ContentReviewStatus],
] = {
    ContentReviewStatus.NOT_REQUIRED: frozenset(),
    ContentReviewStatus.PENDING: frozenset(
        {ContentReviewStatus.APPROVED, ContentReviewStatus.REJECTED},
    ),
    ContentReviewStatus.APPROVED: frozenset(),
    ContentReviewStatus.REJECTED: frozenset(),
}

_PUBLICATION_STATUS_TRANSITIONS: Mapping[
    PublicationStatus,
    frozenset[PublicationStatus],
] = {
    PublicationStatus.PENDING: frozenset(
        {PublicationStatus.IN_PROGRESS, PublicationStatus.CANCELLED},
    ),
    PublicationStatus.IN_PROGRESS: frozenset(
        {
            PublicationStatus.PUBLISHED,
            PublicationStatus.FAILED,
            PublicationStatus.AMBIGUOUS,
        },
    ),
    PublicationStatus.PUBLISHED: frozenset(),
    PublicationStatus.FAILED: frozenset(
        {PublicationStatus.PENDING, PublicationStatus.CANCELLED},
    ),
    PublicationStatus.AMBIGUOUS: frozenset(
        {
            PublicationStatus.PENDING,
            PublicationStatus.PUBLISHED,
            PublicationStatus.CANCELLED,
        },
    ),
    PublicationStatus.CANCELLED: frozenset(),
}


def validate_event_disposition_transition(
    current: EventDisposition,
    target: EventDisposition,
) -> None:
    """Validate an administrative event-disposition transition."""
    _validate_transition(current, target, _EVENT_DISPOSITION_TRANSITIONS)


def validate_scoring_status_transition(
    current: ScoringStatus,
    target: ScoringStatus,
) -> None:
    """Validate a scoring lifecycle transition."""
    _validate_transition(current, target, _SCORING_STATUS_TRANSITIONS)


def validate_content_generation_status_transition(
    current: ContentGenerationStatus,
    target: ContentGenerationStatus,
) -> None:
    """Validate a content-generation lifecycle transition."""
    _validate_transition(current, target, _CONTENT_GENERATION_TRANSITIONS)


def validate_content_review_status_transition(
    current: ContentReviewStatus,
    target: ContentReviewStatus,
) -> None:
    """Validate a content-review lifecycle transition."""
    _validate_transition(current, target, _CONTENT_REVIEW_TRANSITIONS)


def validate_publication_status_transition(
    current: PublicationStatus,
    target: PublicationStatus,
) -> None:
    """Validate a publication lifecycle transition."""
    _validate_transition(current, target, _PUBLICATION_STATUS_TRANSITIONS)


def _validate_transition[T: StrEnum](
    current: T,
    target: T,
    transitions: Mapping[T, frozenset[T]],
) -> None:
    if target not in transitions[current]:
        msg = f"Transition from {current.value!r} to {target.value!r} is not allowed."
        raise InvalidLifecycleTransition(msg)
