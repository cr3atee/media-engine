from __future__ import annotations

from collections.abc import Callable

import pytest

from app.domain.lifecycle import (
    ContentGenerationStatus,
    ContentReviewStatus,
    EventDisposition,
    InvalidLifecycleTransition,
    PublicationStatus,
    ScoringStatus,
    validate_content_generation_status_transition,
    validate_content_review_status_transition,
    validate_event_disposition_transition,
    validate_publication_status_transition,
    validate_scoring_status_transition,
)

type TransitionValidator[T] = Callable[[T, T], None]


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (EventDisposition.ACTIVE, EventDisposition.REVIEW_PENDING),
        (EventDisposition.ACTIVE, EventDisposition.APPROVED),
        (EventDisposition.ACTIVE, EventDisposition.IGNORED),
        (EventDisposition.ACTIVE, EventDisposition.REJECTED),
        (EventDisposition.REVIEW_PENDING, EventDisposition.APPROVED),
        (EventDisposition.REVIEW_PENDING, EventDisposition.IGNORED),
        (EventDisposition.REVIEW_PENDING, EventDisposition.REJECTED),
        (EventDisposition.APPROVED, EventDisposition.IGNORED),
        (EventDisposition.APPROVED, EventDisposition.REJECTED),
    ],
)
def test_approved_event_disposition_transitions_pass(
    current: EventDisposition,
    target: EventDisposition,
) -> None:
    validate_event_disposition_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ScoringStatus.PENDING, ScoringStatus.IN_PROGRESS),
        (ScoringStatus.PENDING, ScoringStatus.SKIPPED),
        (ScoringStatus.IN_PROGRESS, ScoringStatus.SUCCEEDED),
        (ScoringStatus.IN_PROGRESS, ScoringStatus.FAILED),
        (ScoringStatus.FAILED, ScoringStatus.PENDING),
    ],
)
def test_approved_scoring_transitions_pass(
    current: ScoringStatus,
    target: ScoringStatus,
) -> None:
    validate_scoring_status_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ContentGenerationStatus.PENDING, ContentGenerationStatus.IN_PROGRESS),
        (ContentGenerationStatus.PENDING, ContentGenerationStatus.ABANDONED),
        (ContentGenerationStatus.IN_PROGRESS, ContentGenerationStatus.GENERATED),
        (ContentGenerationStatus.IN_PROGRESS, ContentGenerationStatus.FAILED),
        (ContentGenerationStatus.IN_PROGRESS, ContentGenerationStatus.ABANDONED),
    ],
)
def test_approved_generation_transitions_pass(
    current: ContentGenerationStatus,
    target: ContentGenerationStatus,
) -> None:
    validate_content_generation_status_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ContentReviewStatus.PENDING, ContentReviewStatus.APPROVED),
        (ContentReviewStatus.PENDING, ContentReviewStatus.REJECTED),
    ],
)
def test_approved_content_review_transitions_pass(
    current: ContentReviewStatus,
    target: ContentReviewStatus,
) -> None:
    validate_content_review_status_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (PublicationStatus.PENDING, PublicationStatus.IN_PROGRESS),
        (PublicationStatus.PENDING, PublicationStatus.CANCELLED),
        (PublicationStatus.IN_PROGRESS, PublicationStatus.PUBLISHED),
        (PublicationStatus.IN_PROGRESS, PublicationStatus.FAILED),
        (PublicationStatus.IN_PROGRESS, PublicationStatus.AMBIGUOUS),
        (PublicationStatus.FAILED, PublicationStatus.PENDING),
        (PublicationStatus.FAILED, PublicationStatus.CANCELLED),
        (PublicationStatus.AMBIGUOUS, PublicationStatus.PENDING),
        (PublicationStatus.AMBIGUOUS, PublicationStatus.PUBLISHED),
        (PublicationStatus.AMBIGUOUS, PublicationStatus.CANCELLED),
    ],
)
def test_approved_publication_transitions_pass(
    current: PublicationStatus,
    target: PublicationStatus,
) -> None:
    validate_publication_status_transition(current, target)


@pytest.mark.parametrize(
    ("validator", "current", "target"),
    [
        (
            validate_event_disposition_transition,
            EventDisposition.REJECTED,
            EventDisposition.APPROVED,
        ),
        (
            validate_event_disposition_transition,
            EventDisposition.IGNORED,
            EventDisposition.ACTIVE,
        ),
        (
            validate_scoring_status_transition,
            ScoringStatus.SUCCEEDED,
            ScoringStatus.PENDING,
        ),
        (
            validate_content_generation_status_transition,
            ContentGenerationStatus.FAILED,
            ContentGenerationStatus.PENDING,
        ),
        (
            validate_content_review_status_transition,
            ContentReviewStatus.REJECTED,
            ContentReviewStatus.APPROVED,
        ),
        (
            validate_publication_status_transition,
            PublicationStatus.PUBLISHED,
            PublicationStatus.PENDING,
        ),
        (
            validate_publication_status_transition,
            PublicationStatus.CANCELLED,
            PublicationStatus.IN_PROGRESS,
        ),
    ],
)
def test_invalid_and_terminal_transitions_fail[T](
    validator: TransitionValidator[T],
    current: T,
    target: T,
) -> None:
    with pytest.raises(InvalidLifecycleTransition):
        validator(current, target)


@pytest.mark.parametrize(
    ("validator", "state"),
    [
        (validate_event_disposition_transition, EventDisposition.ACTIVE),
        (validate_scoring_status_transition, ScoringStatus.PENDING),
        (
            validate_content_generation_status_transition,
            ContentGenerationStatus.PENDING,
        ),
        (validate_content_review_status_transition, ContentReviewStatus.PENDING),
        (validate_publication_status_transition, PublicationStatus.PENDING),
    ],
)
def test_same_state_is_not_a_transition[T](
    validator: TransitionValidator[T],
    state: T,
) -> None:
    with pytest.raises(InvalidLifecycleTransition):
        validator(state, state)
