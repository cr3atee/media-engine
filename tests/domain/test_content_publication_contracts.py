from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.domain.generated_content import (
    ContentOrigin,
    CreateContentAttempt,
    GeneratedContentAttempt,
    build_content_idempotency_key,
    calculate_content_checksum,
)
from app.domain.lifecycle import (
    ContentGenerationStatus,
    ContentReviewStatus,
    PublicationStatus,
)
from app.domain.processing import ProcessingError, WorkClaim
from app.domain.publications import (
    CreatePublication,
    Publication,
    build_publication_idempotency_key,
)

EVENT_ID = UUID("00000000-0000-0000-0000-000000000013")
CONTENT_ID = UUID("00000000-0000-0000-0000-000000000014")
PUBLICATION_ID = UUID("00000000-0000-0000-0000-000000000015")
CLAIM_ID = UUID("00000000-0000-0000-0000-000000000016")
NOW = datetime(2026, 7, 29, 9, 0, tzinfo=UTC)


def make_content_attempt() -> GeneratedContentAttempt:
    """Create one deterministic pending content attempt."""
    idempotency_key = build_content_idempotency_key(
        event_id=EVENT_ID,
        content_type="telegram_post",
        language="ru",
        prompt_version="price_drop_v1",
        attempt_number=1,
    )
    return GeneratedContentAttempt(
        id=CONTENT_ID,
        event_id=EVENT_ID,
        content_type="telegram_post",
        language="ru",
        origin=ContentOrigin.AI,
        prompt_version="price_drop_v1",
        generation_status=ContentGenerationStatus.PENDING,
        review_status=ContentReviewStatus.PENDING,
        attempt_number=1,
        idempotency_key=idempotency_key,
        created_at=NOW,
        updated_at=NOW,
        provider="fake",
        model="deterministic",
    )


def make_publication() -> Publication:
    """Create one deterministic pending channel-neutral publication."""
    idempotency_key = build_publication_idempotency_key(
        event_id=EVENT_ID,
        content_id=CONTENT_ID,
        channel="preview",
        destination_key="review-channel",
    )
    return Publication(
        id=PUBLICATION_ID,
        event_id=EVENT_ID,
        content_id=CONTENT_ID,
        channel="preview",
        destination_key="review-channel",
        idempotency_key=idempotency_key,
        status=PublicationStatus.PENDING,
        attempt_count=0,
        created_at=NOW,
        updated_at=NOW,
    )


def test_content_attempt_command_builds_deterministic_identity() -> None:
    command = CreateContentAttempt(
        id=CONTENT_ID,
        event_id=EVENT_ID,
        content_type="Telegram_Post",
        language="RU",
        prompt_version="price_drop_v1",
        attempt_number=1,
        provider="fake",
        model="deterministic",
        created_at=NOW,
    )

    assert command.content_type == "telegram_post"
    assert command.language == "ru"
    assert command.idempotency_key == make_content_attempt().idempotency_key


def test_generated_content_requires_matching_checksum() -> None:
    text = "Minecraft Premium: 790 RUB"
    checksum = calculate_content_checksum(text)
    generated = GeneratedContentAttempt(
        id=CONTENT_ID,
        event_id=EVENT_ID,
        content_type="telegram_post",
        language="ru",
        origin=ContentOrigin.AI,
        prompt_version="price_drop_v1",
        generation_status=ContentGenerationStatus.GENERATED,
        review_status=ContentReviewStatus.PENDING,
        attempt_number=1,
        idempotency_key=build_content_idempotency_key(
            event_id=EVENT_ID,
            content_type="telegram_post",
            language="ru",
            prompt_version="price_drop_v1",
            attempt_number=1,
        ),
        created_at=NOW,
        updated_at=NOW + timedelta(seconds=1),
        completed_at=NOW + timedelta(seconds=1),
        content_text=text,
        content_checksum=checksum,
    )

    assert generated.content_checksum == checksum
    assert json.dumps(generated.to_dict(), sort_keys=True)


def test_failed_content_requires_safe_error_details() -> None:
    with pytest.raises(ValueError, match="requires error details"):
        GeneratedContentAttempt(
            id=CONTENT_ID,
            event_id=EVENT_ID,
            content_type="telegram_post",
            language="ru",
            origin=ContentOrigin.AI,
            prompt_version="price_drop_v1",
            generation_status=ContentGenerationStatus.FAILED,
            review_status=ContentReviewStatus.PENDING,
            attempt_number=1,
            idempotency_key=make_content_attempt().idempotency_key,
            created_at=NOW,
            updated_at=NOW,
        )


def test_human_revision_requires_parent_and_contains_no_provider() -> None:
    text = "Reviewed publication"
    parent_id = UUID("00000000-0000-0000-0000-000000000017")
    revision = GeneratedContentAttempt(
        id=CONTENT_ID,
        event_id=EVENT_ID,
        parent_content_id=parent_id,
        content_type="telegram_post",
        language="ru",
        origin=ContentOrigin.HUMAN_EDIT,
        prompt_version="price_drop_v1",
        generation_status=ContentGenerationStatus.GENERATED,
        review_status=ContentReviewStatus.APPROVED,
        attempt_number=2,
        idempotency_key=build_content_idempotency_key(
            event_id=EVENT_ID,
            content_type="telegram_post",
            language="ru",
            prompt_version="price_drop_v1",
            attempt_number=2,
        ),
        created_at=NOW,
        updated_at=NOW,
        completed_at=NOW,
        content_text=text,
        content_checksum=calculate_content_checksum(text),
    )

    assert revision.parent_content_id == parent_id
    assert revision.provider is None
    assert revision.model is None


def test_publication_command_and_model_use_channel_independent_identity() -> None:
    command = CreatePublication(
        id=PUBLICATION_ID,
        event_id=EVENT_ID,
        content_id=CONTENT_ID,
        channel="PREVIEW",
        destination_key="review-channel",
        created_at=NOW,
    )
    publication = make_publication()

    assert command.channel == "preview"
    assert command.idempotency_key == publication.idempotency_key
    assert json.dumps(publication.to_dict(), sort_keys=True)


def test_published_publication_requires_external_message_identity() -> None:
    publication = make_publication()

    with pytest.raises(ValueError, match="requires time and external message ID"):
        Publication(
            id=publication.id,
            event_id=publication.event_id,
            content_id=publication.content_id,
            channel=publication.channel,
            destination_key=publication.destination_key,
            idempotency_key=publication.idempotency_key,
            status=PublicationStatus.PUBLISHED,
            attempt_count=1,
            created_at=NOW,
            updated_at=NOW,
            published_at=NOW,
        )


def test_failed_and_ambiguous_publications_require_error_details() -> None:
    publication = make_publication()

    for status in (PublicationStatus.FAILED, PublicationStatus.AMBIGUOUS):
        with pytest.raises(ValueError, match="requires error details"):
            Publication(
                id=publication.id,
                event_id=publication.event_id,
                content_id=publication.content_id,
                channel=publication.channel,
                destination_key=publication.destination_key,
                idempotency_key=publication.idempotency_key,
                status=status,
                attempt_count=1,
                created_at=NOW,
                updated_at=NOW,
            )


def test_content_publication_claim_and_error_contracts_are_immutable() -> None:
    content = make_content_attempt()
    publication = make_publication()
    claim = WorkClaim(
        token=CLAIM_ID,
        worker_id="worker-1",
        claimed_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=1),
        version=2,
    )
    error = ProcessingError(code="timeout", summary="Provider timed out")

    with pytest.raises(FrozenInstanceError):
        content.attempt_number = 2  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        publication.status = PublicationStatus.PUBLISHED  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        claim.worker_id = "worker-2"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        error.code = "changed"  # type: ignore[misc]
