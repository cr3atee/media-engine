from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass(slots=True, frozen=True)
class CursorPosition:
    """Decoded position of the last item returned by a read query."""

    resource: str
    sort: str
    direction: str
    timestamp: datetime
    item_id: UUID
    filter_hash: str


@dataclass(slots=True, frozen=True)
class PageRequest:
    """Validated keyset page request passed to a query repository."""

    limit: int
    sort: str
    direction: str
    filter_hash: str
    cursor: CursorPosition | None = None


@dataclass(slots=True, frozen=True)
class ReadPage[TRead]:
    """Immutable page returned by a read-side query repository."""

    items: tuple[TRead, ...]
    next_cursor: CursorPosition | None


@dataclass(slots=True, frozen=True)
class SnapshotRead:
    """Safe read projection of one price snapshot identity."""

    marketplace: str
    external_id: str
    collected_at: datetime
    price: Decimal
    currency: str


@dataclass(slots=True, frozen=True)
class RelatedSummary:
    """Small status summary for related durable records."""

    count: int
    statuses: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class PriceDropPayloadRead:
    """Typed read projection of a persistent price-drop payload."""

    payload_type: str
    version: int
    title: str | None
    url: str | None
    old_price: Decimal
    new_price: Decimal
    currency: str
    absolute_difference: Decimal
    percentage: Decimal
    previous_snapshot: SnapshotRead
    current_snapshot: SnapshotRead


@dataclass(slots=True, frozen=True)
class EventRead:
    """Immutable administration read projection for one market event."""

    id: UUID
    identity_key: str
    identity_version: int
    event_type: str
    marketplace: str
    external_id: str
    canonical_product_id: UUID | None
    payload: PriceDropPayloadRead
    occurred_at: datetime
    detected_at: datetime
    created_at: datetime
    disposition: str
    scoring_status: str
    score: int | None
    scoring_attempt_count: int
    next_retry_at: datetime | None
    error_code: str | None
    error_summary: str | None
    version: int
    content_summary: RelatedSummary
    publication_summary: RelatedSummary


@dataclass(slots=True, frozen=True)
class ContentRead:
    """Immutable administration read projection for one content attempt."""

    id: UUID
    event_id: UUID
    parent_content_id: UUID | None
    content_type: str
    language: str
    origin: str
    provider: str | None
    model: str | None
    prompt_version: str
    content_text: str | None
    generation_status: str
    review_status: str
    attempt_number: int
    content_checksum: str | None
    next_retry_at: datetime | None
    error_code: str | None
    error_summary: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    version: int
    publication_summary: RelatedSummary


@dataclass(slots=True, frozen=True)
class PublicationRead:
    """Immutable administration read projection for one publication."""

    id: UUID
    event_id: UUID
    content_id: UUID
    channel: str
    destination_reference: str
    status: str
    attempt_count: int
    external_message_id: str | None
    scheduled_at: datetime | None
    next_retry_at: datetime | None
    published_at: datetime | None
    error_code: str | None
    error_summary: str | None
    created_at: datetime
    updated_at: datetime
    version: int


@dataclass(slots=True, frozen=True)
class DashboardWindow:
    """UTC time window for bounded operational dashboard aggregates."""

    starts_at: datetime
    ends_at: datetime


@dataclass(slots=True, frozen=True)
class DashboardSummaryRead:
    """Immutable read projection for administration dashboard counters."""

    window: DashboardWindow
    total_new_market_events: int
    events_awaiting_scoring: int
    scoring_failures: int
    generated_content_pending: int
    generated_content_failed: int
    generated_content_awaiting_review: int
    approved_content_awaiting_publication: int
    publications_pending: int
    publications_retryable: int
    publications_permanently_failed: int
    publications_ambiguous: int
    publications_published: int
    latest_event_activity_at: datetime | None
    latest_publication_at: datetime | None


@dataclass(slots=True, frozen=True)
class EventQuery:
    """Typed filters supported by the event read API."""

    marketplace: str | None = None
    event_type: str | None = None
    disposition: str | None = None
    scoring_status: str | None = None
    content_generation_status: str | None = None
    review_status: str | None = None
    publication_status: str | None = None
    min_score: int | None = None
    external_id: str | None = None
    search: str | None = None
    canonical_product_id: UUID | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    detected_from: datetime | None = None
    detected_to: datetime | None = None
    has_content: bool | None = None
    has_publication: bool | None = None
    has_failure: bool | None = None
    ambiguous_only: bool = False


@dataclass(slots=True, frozen=True)
class ContentQuery:
    """Typed filters supported by the generated-content read API."""

    event_id: UUID | None = None
    search: str | None = None
    generation_status: str | None = None
    review_status: str | None = None
    attempt_number: int | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    completed_from: datetime | None = None
    completed_to: datetime | None = None
    has_publication: bool | None = None
    failed_only: bool = False


@dataclass(slots=True, frozen=True)
class PublicationQuery:
    """Typed filters supported by the publication read API."""

    event_id: UUID | None = None
    content_id: UUID | None = None
    channel: str | None = None
    status: str | None = None
    retryable: bool | None = None
    permanent_failure: bool | None = None
    ambiguous_only: bool = False
    scheduled_from: datetime | None = None
    scheduled_to: datetime | None = None
    published_from: datetime | None = None
    published_to: datetime | None = None
    min_attempts: int | None = None
    max_attempts: int | None = None
