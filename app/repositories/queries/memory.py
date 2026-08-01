from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

from app.repositories.queries.contracts import (
    DashboardQueryRepository,
    GeneratedContentQueryRepository,
    MarketEventQueryRepository,
    PublicationQueryRepository,
)
from app.repositories.queries.cursors import (
    content_cursor,
    event_cursor,
    publication_cursor,
)
from app.repositories.queries.models import (
    ContentQuery,
    ContentRead,
    DashboardSummaryRead,
    DashboardWindow,
    EventQuery,
    EventRead,
    PageRequest,
    PublicationQuery,
    PublicationRead,
    ReadPage,
)


class MemoryMarketEventQueryRepository(MarketEventQueryRepository):
    """Deterministic in-memory event query repository for API tests."""

    def __init__(self, events: Iterable[EventRead] = ()) -> None:
        """Store an isolated immutable snapshot of the supplied projections."""
        self._events = tuple(events)

    async def list_events(
        self,
        query: EventQuery,
        page: PageRequest,
    ) -> ReadPage[EventRead]:
        """Return a filtered keyset page without simulating SQL."""
        items = [event for event in self._events if _event_matches(event, query)]
        items.sort(
            key=lambda event: (
                event.created_at if page.sort == "created_at" else event.detected_at,
                event.id,
            ),
            reverse=page.direction == "desc",
        )
        items = _after_cursor(items, page)
        has_next = len(items) > page.limit
        selected = tuple(items[: page.limit])
        next_cursor = None
        if has_next and selected:
            next_cursor = event_cursor(selected[-1], page)
        return ReadPage(items=selected, next_cursor=next_cursor)

    async def get_event(self, event_id: UUID) -> EventRead | None:
        """Return one event projection by identifier."""
        return next((event for event in self._events if event.id == event_id), None)


class MemoryGeneratedContentQueryRepository(GeneratedContentQueryRepository):
    """Deterministic in-memory content query repository for API tests."""

    def __init__(self, contents: Iterable[ContentRead] = ()) -> None:
        """Store an isolated immutable snapshot of the supplied projections."""
        self._contents = tuple(contents)

    async def list_content(
        self,
        query: ContentQuery,
        page: PageRequest,
    ) -> ReadPage[ContentRead]:
        """Return a filtered keyset page without reproducing SQL behavior."""
        items = [
            content for content in self._contents if _content_matches(content, query)
        ]
        items.sort(
            key=lambda content: (
                content.updated_at if page.sort == "updated_at" else content.created_at,
                content.id,
            ),
            reverse=page.direction == "desc",
        )
        items = _after_cursor(items, page)
        has_next = len(items) > page.limit
        selected = tuple(items[: page.limit])
        next_cursor = None
        if has_next and selected:
            next_cursor = content_cursor(selected[-1], page)
        return ReadPage(items=selected, next_cursor=next_cursor)

    async def get_content(self, content_id: UUID) -> ContentRead | None:
        """Return one content projection by identifier."""
        return next(
            (content for content in self._contents if content.id == content_id),
            None,
        )


class MemoryPublicationQueryRepository(PublicationQueryRepository):
    """Deterministic in-memory publication query repository for API tests."""

    def __init__(self, publications: Iterable[PublicationRead] = ()) -> None:
        """Store an isolated immutable snapshot of the supplied projections."""
        self._publications = tuple(publications)

    async def list_publications(
        self,
        query: PublicationQuery,
        page: PageRequest,
    ) -> ReadPage[PublicationRead]:
        """Return a filtered keyset page without reproducing SQL behavior."""
        items = [
            publication
            for publication in self._publications
            if _publication_matches(publication, query)
        ]
        items.sort(
            key=lambda publication: (publication.created_at, publication.id),
            reverse=page.direction == "desc",
        )
        items = _after_cursor(items, page)
        has_next = len(items) > page.limit
        selected = tuple(items[: page.limit])
        next_cursor = None
        if has_next and selected:
            next_cursor = publication_cursor(selected[-1], page)
        return ReadPage(items=selected, next_cursor=next_cursor)

    async def get_publication(self, publication_id: UUID) -> PublicationRead | None:
        """Return one publication projection by identifier."""
        return next(
            (
                publication
                for publication in self._publications
                if publication.id == publication_id
            ),
            None,
        )


class MemoryDashboardQueryRepository(DashboardQueryRepository):
    """Deterministic in-memory dashboard aggregates for API tests."""

    def __init__(
        self,
        *,
        events: Iterable[EventRead] = (),
        content: Iterable[ContentRead] = (),
        publications: Iterable[PublicationRead] = (),
    ) -> None:
        """Store isolated immutable snapshots of the supplied projections."""
        self._events = tuple(events)
        self._content = tuple(content)
        self._publications = tuple(publications)

    async def get_summary(self, window: DashboardWindow) -> DashboardSummaryRead:
        """Return aggregate counters over the configured in-memory rows."""
        events = [
            event for event in self._events if _inside_window(event.created_at, window)
        ]
        content = [
            item for item in self._content if _inside_window(item.created_at, window)
        ]
        publications = [
            item
            for item in self._publications
            if _inside_window(item.created_at, window)
        ]
        return DashboardSummaryRead(
            window=window,
            total_new_market_events=len(events),
            events_awaiting_scoring=sum(
                event.scoring_status == "pending" for event in events
            ),
            scoring_failures=sum(event.scoring_status == "failed" for event in events),
            generated_content_pending=sum(
                item.generation_status == "pending" for item in content
            ),
            generated_content_failed=sum(
                item.generation_status == "failed" for item in content
            ),
            generated_content_awaiting_review=sum(
                item.generation_status == "generated"
                and item.review_status == "pending"
                for item in content
            ),
            approved_content_awaiting_publication=sum(
                _content_awaits_publication(item, publications) for item in content
            ),
            publications_pending=sum(item.status == "pending" for item in publications),
            publications_retryable=sum(
                item.status == "failed" and item.next_retry_at is not None
                for item in publications
            ),
            publications_permanently_failed=sum(
                item.status == "failed" and item.next_retry_at is None
                for item in publications
            ),
            publications_ambiguous=sum(
                item.status == "ambiguous" for item in publications
            ),
            publications_published=sum(
                item.status == "published" for item in publications
            ),
            latest_event_activity_at=max(
                (event.created_at for event in events),
                default=None,
            ),
            latest_publication_at=max(
                (
                    item.published_at
                    for item in publications
                    if item.published_at is not None
                ),
                default=None,
            ),
        )


def _event_matches(event: EventRead, query: EventQuery) -> bool:
    if query.marketplace is not None and event.marketplace != query.marketplace:
        return False
    if query.event_type is not None and event.event_type != query.event_type:
        return False
    if query.disposition is not None and event.disposition != query.disposition:
        return False
    if (
        query.scoring_status is not None
        and event.scoring_status != query.scoring_status
    ):
        return False
    if (
        query.content_generation_status is not None
        and query.content_generation_status not in event.content_summary.statuses
    ):
        return False
    if (
        query.publication_status is not None
        and query.publication_status not in event.publication_summary.statuses
    ):
        return False
    if query.min_score is not None and (
        event.score is None or event.score < query.min_score
    ):
        return False
    if query.external_id is not None and event.external_id != query.external_id:
        return False
    if query.search is not None:
        needle = query.search.casefold()
        if not any(
            needle in value.casefold()
            for value in (
                event.external_id,
                event.payload.title or "",
                event.payload.url or "",
            )
        ):
            return False
    if (
        query.canonical_product_id is not None
        and event.canonical_product_id != query.canonical_product_id
    ):
        return False
    if query.created_from is not None and event.created_at < query.created_from:
        return False
    if query.created_to is not None and event.created_at > query.created_to:
        return False
    if query.detected_from is not None and event.detected_at < query.detected_from:
        return False
    if query.detected_to is not None and event.detected_at > query.detected_to:
        return False
    if query.has_content is not None and (
        (event.content_summary.count > 0) != query.has_content
    ):
        return False
    if query.has_publication is not None and (
        (event.publication_summary.count > 0) != query.has_publication
    ):
        return False
    has_failure = (
        event.scoring_status == "failed"
        or "failed" in event.content_summary.statuses
        or "failed" in event.publication_summary.statuses
        or "ambiguous" in event.publication_summary.statuses
    )
    if query.has_failure is not None and has_failure != query.has_failure:
        return False
    if query.ambiguous_only and "ambiguous" not in event.publication_summary.statuses:
        return False
    return True


def _content_matches(content: ContentRead, query: ContentQuery) -> bool:
    if query.event_id is not None and content.event_id != query.event_id:
        return False
    if (
        query.search is not None
        and query.search.casefold() not in (content.content_text or "").casefold()
    ):
        return False
    if (
        query.generation_status is not None
        and content.generation_status != query.generation_status
    ):
        return False
    if query.review_status is not None and content.review_status != query.review_status:
        return False
    if (
        query.attempt_number is not None
        and content.attempt_number != query.attempt_number
    ):
        return False
    if query.created_from is not None and content.created_at < query.created_from:
        return False
    if query.created_to is not None and content.created_at > query.created_to:
        return False
    if query.completed_from is not None and (
        content.completed_at is None or content.completed_at < query.completed_from
    ):
        return False
    if query.completed_to is not None and (
        content.completed_at is None or content.completed_at > query.completed_to
    ):
        return False
    if query.has_publication is not None and (
        (content.publication_summary.count > 0) != query.has_publication
    ):
        return False
    return not query.failed_only or content.generation_status == "failed"


def _publication_matches(
    publication: PublicationRead,
    query: PublicationQuery,
) -> bool:
    if query.event_id is not None and publication.event_id != query.event_id:
        return False
    if query.content_id is not None and publication.content_id != query.content_id:
        return False
    if query.channel is not None and publication.channel != query.channel:
        return False
    if query.status is not None and publication.status != query.status:
        return False
    is_failed = publication.status == "failed"
    is_retryable = is_failed and publication.next_retry_at is not None
    is_permanent = is_failed and publication.next_retry_at is None
    if query.retryable is not None and is_retryable != query.retryable:
        return False
    if query.permanent_failure is not None and is_permanent != query.permanent_failure:
        return False
    if query.ambiguous_only and publication.status != "ambiguous":
        return False
    if query.scheduled_from is not None and (
        publication.scheduled_at is None
        or publication.scheduled_at < query.scheduled_from
    ):
        return False
    if query.scheduled_to is not None and (
        publication.scheduled_at is None
        or publication.scheduled_at > query.scheduled_to
    ):
        return False
    if query.published_from is not None and (
        publication.published_at is None
        or publication.published_at < query.published_from
    ):
        return False
    if query.published_to is not None and (
        publication.published_at is None
        or publication.published_at > query.published_to
    ):
        return False
    if (
        query.min_attempts is not None
        and publication.attempt_count < query.min_attempts
    ):
        return False
    if (
        query.max_attempts is not None
        and publication.attempt_count > query.max_attempts
    ):
        return False
    return True


def _after_cursor[TRead](items: list[TRead], page: PageRequest) -> list[TRead]:
    if page.cursor is None:
        return items
    cursor = page.cursor
    result: list[TRead] = []
    for item in items:
        timestamp, item_id = _item_position(item, page.sort)
        if page.direction == "asc":
            after = (timestamp, item_id) > (cursor.timestamp, cursor.item_id)
        else:
            after = (timestamp, item_id) < (cursor.timestamp, cursor.item_id)
        if after:
            result.append(item)
    return result


def _item_position[TRead](item: TRead, sort: str) -> tuple[object, UUID]:
    if isinstance(item, EventRead):
        timestamp = item.created_at if sort == "created_at" else item.detected_at
        return timestamp, item.id
    if isinstance(item, ContentRead):
        timestamp = item.updated_at if sort == "updated_at" else item.created_at
        return timestamp, item.id
    if isinstance(item, PublicationRead):
        return item.created_at, item.id
    raise TypeError(f"Unsupported read projection: {type(item)!r}.")


def _inside_window(value: datetime, window: DashboardWindow) -> bool:
    return window.starts_at <= value < window.ends_at


def _content_awaits_publication(
    content: ContentRead,
    publications: list[PublicationRead],
) -> bool:
    return (
        content.generation_status == "generated"
        and content.review_status == "approved"
        and any(
            publication.content_id == content.id
            and publication.status in {"pending", "in_progress", "failed", "ambiguous"}
            for publication in publications
        )
    )
