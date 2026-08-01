from __future__ import annotations

from typing import Literal, cast

from app.api.schemas.common import RelatedSummaryResponse
from app.api.schemas.content import ContentResponse
from app.api.schemas.events import (
    EventResponse,
    PriceDropPayloadResponse,
    SnapshotResponse,
)
from app.api.schemas.publications import PublicationResponse
from app.repositories.queries.models import (
    ContentRead,
    EventRead,
    PublicationRead,
    RelatedSummary,
    SnapshotRead,
)
from app.repositories.queries.safety import safe_error, safe_label


def event_response(event: EventRead) -> EventResponse:
    """Map an immutable event projection to its public DTO."""
    error_code, error_summary = safe_error(event.error_code, event.error_summary)
    return EventResponse(
        id=event.id,
        identity_key=event.identity_key,
        identity_version=event.identity_version,
        event_type=cast(Literal["price_drop"], event.event_type),
        marketplace=event.marketplace,
        external_id=event.external_id,
        canonical_product_id=event.canonical_product_id,
        payload=PriceDropPayloadResponse(
            type=cast(Literal["price_drop"], event.payload.payload_type),
            version=event.payload.version,
            title=event.payload.title,
            url=event.payload.url,
            old_price=_decimal_string(event.payload.old_price),
            new_price=_decimal_string(event.payload.new_price),
            currency=event.payload.currency,
            absolute_difference=_decimal_string(
                event.payload.absolute_difference,
            ),
            percentage=_decimal_string(event.payload.percentage),
            previous_snapshot=snapshot_response(event.payload.previous_snapshot),
            current_snapshot=snapshot_response(event.payload.current_snapshot),
        ),
        occurred_at=event.occurred_at,
        detected_at=event.detected_at,
        created_at=event.created_at,
        disposition=event.disposition,
        scoring_status=event.scoring_status,
        score=event.score,
        scoring_attempt_count=event.scoring_attempt_count,
        next_retry_at=event.next_retry_at,
        error_code=error_code,
        error_summary=error_summary,
        version=event.version,
        content_summary=summary_response(event.content_summary),
        publication_summary=summary_response(event.publication_summary),
    )


def content_response(content: ContentRead) -> ContentResponse:
    """Map an immutable content projection to its public DTO."""
    error_code, error_summary = safe_error(
        content.error_code,
        content.error_summary,
    )
    return ContentResponse(
        id=content.id,
        event_id=content.event_id,
        parent_content_id=content.parent_content_id,
        content_type=content.content_type,
        language=content.language,
        origin=content.origin,
        provider=safe_label(content.provider),
        model=safe_label(content.model, maximum=255),
        prompt_version=content.prompt_version,
        content_text=content.content_text,
        generation_status=content.generation_status,
        review_status=content.review_status,
        attempt_number=content.attempt_number,
        content_checksum=content.content_checksum,
        next_retry_at=content.next_retry_at,
        error_code=error_code,
        error_summary=error_summary,
        created_at=content.created_at,
        updated_at=content.updated_at,
        completed_at=content.completed_at,
        version=content.version,
        publication_summary=summary_response(content.publication_summary),
    )


def publication_response(publication: PublicationRead) -> PublicationResponse:
    """Map an immutable publication projection to its public DTO."""
    error_code, error_summary = safe_error(
        publication.error_code,
        publication.error_summary,
    )
    return PublicationResponse(
        id=publication.id,
        event_id=publication.event_id,
        content_id=publication.content_id,
        channel=publication.channel,
        destination_reference=publication.destination_reference,
        status=publication.status,
        attempt_count=publication.attempt_count,
        external_message_id=publication.external_message_id,
        scheduled_at=publication.scheduled_at,
        next_retry_at=publication.next_retry_at,
        published_at=publication.published_at,
        error_code=error_code,
        error_summary=error_summary,
        created_at=publication.created_at,
        updated_at=publication.updated_at,
        version=publication.version,
    )


def snapshot_response(snapshot: SnapshotRead) -> SnapshotResponse:
    """Map one snapshot projection to a string-safe money DTO."""
    return SnapshotResponse(
        marketplace=snapshot.marketplace,
        external_id=snapshot.external_id,
        collected_at=snapshot.collected_at,
        price=_decimal_string(snapshot.price),
        currency=snapshot.currency,
    )


def summary_response(summary: RelatedSummary) -> RelatedSummaryResponse:
    """Map one related-resource summary to its public DTO."""
    return RelatedSummaryResponse(
        count=summary.count,
        statuses=list(summary.statuses),
    )


def _decimal_string(value: object) -> str:
    return format(value, "f")
