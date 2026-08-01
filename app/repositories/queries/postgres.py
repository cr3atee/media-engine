from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, asc, desc, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.models.generated_content_record import GeneratedContentRecord
from app.models.market_event_record import MarketEventRecord
from app.models.price_snapshot_record import PriceSnapshotRecord
from app.models.publication_record import PublicationRecord
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
    CursorPosition,
    DashboardSummaryRead,
    DashboardWindow,
    EventQuery,
    EventRead,
    PageRequest,
    PriceDropPayloadRead,
    PublicationQuery,
    PublicationRead,
    ReadPage,
    RelatedSummary,
    SnapshotRead,
)
from app.repositories.queries.safety import (
    destination_reference,
    safe_error,
    safe_label,
)


class PostgresMarketEventQueryRepository(MarketEventQueryRepository):
    """PostgreSQL read projections for durable market events."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the query repository to a caller-owned session."""
        self._session = session

    async def list_events(
        self,
        query: EventQuery,
        page: PageRequest,
    ) -> ReadPage[EventRead]:
        """Return a keyset-paginated event projection."""
        statement = self._statement(query, page)
        result = await self._session.execute(statement.limit(page.limit + 1))
        rows = result.all()
        has_next = len(rows) > page.limit
        selected = rows[: page.limit]
        items = tuple(_event_from_row(row) for row in selected)
        next_cursor = event_cursor(items[-1], page) if has_next and items else None
        return ReadPage(items=items, next_cursor=next_cursor)

    async def get_event(self, event_id: UUID) -> EventRead | None:
        """Return one event projection by identifier."""
        statement = self._statement(
            EventQuery(),
            PageRequest(
                limit=1,
                sort="detected_at",
                direction="desc",
                filter_hash="",
            ),
        ).where(MarketEventRecord.id == event_id)
        result = await self._session.execute(statement.limit(1))
        row = result.one_or_none()
        return _event_from_row(row) if row is not None else None

    def _statement(
        self,
        query: EventQuery,
        page: PageRequest,
    ) -> Any:
        previous = aliased(PriceSnapshotRecord)
        current = aliased(PriceSnapshotRecord)
        content_count = _count_for_event(GeneratedContentRecord)
        content_statuses = _statuses_for_event(
            GeneratedContentRecord.generation_status,
            GeneratedContentRecord,
        )
        publication_count = _count_for_event(PublicationRecord)
        publication_statuses = _statuses_for_event(
            PublicationRecord.publication_status,
            PublicationRecord,
        )
        statement = (
            select(
                MarketEventRecord,
                previous,
                current,
                content_count.label("content_count"),
                content_statuses.label("content_statuses"),
                publication_count.label("publication_count"),
                publication_statuses.label("publication_statuses"),
            )
            .join(
                previous,
                MarketEventRecord.previous_snapshot_id == previous.id,
            )
            .join(
                current,
                MarketEventRecord.current_snapshot_id == current.id,
            )
            .where(*_event_filters(query))
        )
        timestamp_column = _event_sort_column(page.sort)
        if page.cursor is not None:
            statement = statement.where(
                _keyset_after(
                    timestamp_column,
                    MarketEventRecord.id,
                    page.cursor,
                    page.direction,
                )
            )
        order = (
            (desc(timestamp_column), desc(MarketEventRecord.id))
            if page.direction == "desc"
            else (asc(timestamp_column), asc(MarketEventRecord.id))
        )
        return statement.order_by(*order)


class PostgresGeneratedContentQueryRepository(GeneratedContentQueryRepository):
    """PostgreSQL read projections for generated content attempts."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the query repository to a caller-owned session."""
        self._session = session

    async def list_content(
        self,
        query: ContentQuery,
        page: PageRequest,
    ) -> ReadPage[ContentRead]:
        """Return a keyset-paginated content projection."""
        statement = self._statement(query, page)
        result = await self._session.execute(statement.limit(page.limit + 1))
        rows = result.all()
        has_next = len(rows) > page.limit
        selected = rows[: page.limit]
        items = tuple(_content_from_row(row) for row in selected)
        next_cursor = content_cursor(items[-1], page) if has_next and items else None
        return ReadPage(items=items, next_cursor=next_cursor)

    async def get_content(self, content_id: UUID) -> ContentRead | None:
        """Return one content projection by identifier."""
        statement = self._statement(
            ContentQuery(),
            PageRequest(
                limit=1,
                sort="created_at",
                direction="desc",
                filter_hash="",
            ),
        ).where(GeneratedContentRecord.id == content_id)
        result = await self._session.execute(statement.limit(1))
        row = result.one_or_none()
        return _content_from_row(row) if row is not None else None

    def _statement(
        self,
        query: ContentQuery,
        page: PageRequest,
    ) -> Any:
        publication_count = _count_for_content()
        publication_statuses = _statuses_for_content(
            PublicationRecord.publication_status,
        )
        statement = select(
            GeneratedContentRecord,
            publication_count.label("publication_count"),
            publication_statuses.label("publication_statuses"),
        ).where(*_content_filters(query))
        timestamp_column = _content_sort_column(page.sort)
        if page.cursor is not None:
            statement = statement.where(
                _keyset_after(
                    timestamp_column,
                    GeneratedContentRecord.id,
                    page.cursor,
                    page.direction,
                )
            )
        order = (
            (desc(timestamp_column), desc(GeneratedContentRecord.id))
            if page.direction == "desc"
            else (asc(timestamp_column), asc(GeneratedContentRecord.id))
        )
        return statement.order_by(*order)


class PostgresPublicationQueryRepository(PublicationQueryRepository):
    """PostgreSQL read projections for publication intents."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the query repository to a caller-owned session."""
        self._session = session

    async def list_publications(
        self,
        query: PublicationQuery,
        page: PageRequest,
    ) -> ReadPage[PublicationRead]:
        """Return a keyset-paginated publication projection."""
        statement = self._statement(query, page)
        result = await self._session.execute(statement.limit(page.limit + 1))
        rows = result.scalars().all()
        has_next = len(rows) > page.limit
        selected = rows[: page.limit]
        items = tuple(_publication_from_record(record) for record in selected)
        next_cursor = (
            publication_cursor(items[-1], page) if has_next and items else None
        )
        return ReadPage(items=items, next_cursor=next_cursor)

    async def get_publication(self, publication_id: UUID) -> PublicationRead | None:
        """Return one publication projection by identifier."""
        result = await self._session.execute(
            select(PublicationRecord).where(PublicationRecord.id == publication_id)
        )
        record = result.scalar_one_or_none()
        return _publication_from_record(record) if record is not None else None

    def _statement(
        self,
        query: PublicationQuery,
        page: PageRequest,
    ) -> Any:
        statement = select(PublicationRecord).where(*_publication_filters(query))
        timestamp_column = PublicationRecord.created_at
        if page.cursor is not None:
            statement = statement.where(
                _keyset_after(
                    timestamp_column,
                    PublicationRecord.id,
                    page.cursor,
                    page.direction,
                )
            )
        order = (
            (desc(timestamp_column), desc(PublicationRecord.id))
            if page.direction == "desc"
            else (asc(timestamp_column), asc(PublicationRecord.id))
        )
        return statement.order_by(*order)


class PostgresDashboardQueryRepository(DashboardQueryRepository):
    """PostgreSQL bounded aggregate queries for the admin dashboard."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the dashboard repository to a caller-owned read session."""
        self._session = session

    async def get_summary(self, window: DashboardWindow) -> DashboardSummaryRead:
        """Return one bounded operational dashboard summary."""
        return DashboardSummaryRead(
            window=window,
            total_new_market_events=await self._count(
                select(func.count(MarketEventRecord.id)).where(
                    _window_filter(MarketEventRecord.created_at, window)
                )
            ),
            events_awaiting_scoring=await self._count(
                select(func.count(MarketEventRecord.id)).where(
                    _window_filter(MarketEventRecord.created_at, window),
                    MarketEventRecord.scoring_status == "pending",
                )
            ),
            scoring_failures=await self._count(
                select(func.count(MarketEventRecord.id)).where(
                    _window_filter(MarketEventRecord.created_at, window),
                    MarketEventRecord.scoring_status == "failed",
                )
            ),
            generated_content_pending=await self._count(
                select(func.count(GeneratedContentRecord.id)).where(
                    _window_filter(GeneratedContentRecord.created_at, window),
                    GeneratedContentRecord.generation_status == "pending",
                )
            ),
            generated_content_failed=await self._count(
                select(func.count(GeneratedContentRecord.id)).where(
                    _window_filter(GeneratedContentRecord.created_at, window),
                    GeneratedContentRecord.generation_status == "failed",
                )
            ),
            generated_content_awaiting_review=await self._count(
                select(func.count(GeneratedContentRecord.id)).where(
                    _window_filter(GeneratedContentRecord.created_at, window),
                    GeneratedContentRecord.generation_status == "generated",
                    GeneratedContentRecord.review_status == "pending",
                )
            ),
            approved_content_awaiting_publication=await self._count(
                select(func.count(GeneratedContentRecord.id)).where(
                    _window_filter(GeneratedContentRecord.created_at, window),
                    GeneratedContentRecord.generation_status == "generated",
                    GeneratedContentRecord.review_status == "approved",
                    exists(
                        select(1).where(
                            PublicationRecord.content_id == GeneratedContentRecord.id,
                            PublicationRecord.publication_status.in_(
                                ("pending", "in_progress", "failed", "ambiguous")
                            ),
                        )
                    ),
                )
            ),
            publications_pending=await self._count_publications(
                window,
                PublicationRecord.publication_status == "pending",
            ),
            publications_retryable=await self._count_publications(
                window,
                PublicationRecord.publication_status == "failed",
                PublicationRecord.next_retry_at.is_not(None),
            ),
            publications_permanently_failed=await self._count_publications(
                window,
                PublicationRecord.publication_status == "failed",
                PublicationRecord.next_retry_at.is_(None),
            ),
            publications_ambiguous=await self._count_publications(
                window,
                PublicationRecord.publication_status == "ambiguous",
            ),
            publications_published=await self._count_publications(
                window,
                PublicationRecord.publication_status == "published",
            ),
            latest_event_activity_at=await self._max_timestamp(
                select(func.max(MarketEventRecord.created_at)).where(
                    _window_filter(MarketEventRecord.created_at, window)
                )
            ),
            latest_publication_at=await self._max_timestamp(
                select(func.max(PublicationRecord.published_at)).where(
                    PublicationRecord.published_at.is_not(None),
                    _window_filter(PublicationRecord.published_at, window),
                )
            ),
        )

    async def _count(self, statement: Any) -> int:
        result = await self._session.execute(statement)
        return int(result.scalar_one() or 0)

    async def _count_publications(
        self,
        window: DashboardWindow,
        *filters: ColumnElement[bool],
    ) -> int:
        return await self._count(
            select(func.count(PublicationRecord.id)).where(
                _window_filter(PublicationRecord.created_at, window),
                *filters,
            )
        )

    async def _max_timestamp(self, statement: Any) -> datetime | None:
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()


def _event_filters(query: EventQuery) -> tuple[ColumnElement[bool], ...]:
    filters: list[ColumnElement[bool]] = []
    if query.marketplace is not None:
        filters.append(MarketEventRecord.marketplace == query.marketplace)
    if query.event_type is not None:
        filters.append(MarketEventRecord.event_type == query.event_type)
    if query.disposition is not None:
        filters.append(MarketEventRecord.disposition == query.disposition)
    if query.scoring_status is not None:
        filters.append(MarketEventRecord.scoring_status == query.scoring_status)
    if query.content_generation_status is not None:
        filters.append(
            exists(
                select(1).where(
                    GeneratedContentRecord.event_id == MarketEventRecord.id,
                    GeneratedContentRecord.generation_status
                    == query.content_generation_status,
                )
            )
        )
    if query.review_status is not None:
        filters.append(
            exists(
                select(1).where(
                    GeneratedContentRecord.event_id == MarketEventRecord.id,
                    GeneratedContentRecord.review_status == query.review_status,
                )
            )
        )
    if query.publication_status is not None:
        filters.append(
            exists(
                select(1).where(
                    PublicationRecord.event_id == MarketEventRecord.id,
                    PublicationRecord.publication_status == query.publication_status,
                )
            )
        )
    if query.min_score is not None:
        filters.append(MarketEventRecord.score >= query.min_score)
    if query.external_id is not None:
        filters.append(MarketEventRecord.external_id == query.external_id)
    if query.search is not None:
        pattern = _like_pattern(query.search)
        filters.append(
            or_(
                MarketEventRecord.external_id.ilike(pattern, escape="\\"),
                MarketEventRecord.title.ilike(pattern, escape="\\"),
                MarketEventRecord.url.ilike(pattern, escape="\\"),
            )
        )
    if query.canonical_product_id is not None:
        filters.append(
            MarketEventRecord.canonical_product_id == query.canonical_product_id
        )
    if query.created_from is not None:
        filters.append(MarketEventRecord.created_at >= query.created_from)
    if query.created_to is not None:
        filters.append(MarketEventRecord.created_at <= query.created_to)
    if query.detected_from is not None:
        filters.append(MarketEventRecord.detected_at >= query.detected_from)
    if query.detected_to is not None:
        filters.append(MarketEventRecord.detected_at <= query.detected_to)
    if query.has_content is not None:
        condition = exists(
            select(1).where(GeneratedContentRecord.event_id == MarketEventRecord.id)
        )
        filters.append(condition if query.has_content else ~condition)
    if query.has_publication is not None:
        condition = exists(
            select(1).where(PublicationRecord.event_id == MarketEventRecord.id)
        )
        filters.append(condition if query.has_publication else ~condition)
    if query.has_failure is not None:
        failure_condition: ColumnElement[bool] = _event_failure_exists()
        filters.append(failure_condition if query.has_failure else ~failure_condition)
    if query.ambiguous_only:
        filters.append(
            exists(
                select(1).where(
                    PublicationRecord.event_id == MarketEventRecord.id,
                    PublicationRecord.publication_status == "ambiguous",
                )
            )
        )
    return tuple(filters)


def _content_filters(query: ContentQuery) -> tuple[ColumnElement[bool], ...]:
    filters: list[ColumnElement[bool]] = []
    if query.event_id is not None:
        filters.append(GeneratedContentRecord.event_id == query.event_id)
    if query.search is not None:
        filters.append(
            GeneratedContentRecord.content_text.ilike(
                _like_pattern(query.search),
                escape="\\",
            )
        )
    if query.generation_status is not None:
        filters.append(
            GeneratedContentRecord.generation_status == query.generation_status
        )
    if query.review_status is not None:
        filters.append(GeneratedContentRecord.review_status == query.review_status)
    if query.attempt_number is not None:
        filters.append(GeneratedContentRecord.attempt_number == query.attempt_number)
    if query.created_from is not None:
        filters.append(GeneratedContentRecord.created_at >= query.created_from)
    if query.created_to is not None:
        filters.append(GeneratedContentRecord.created_at <= query.created_to)
    if query.completed_from is not None:
        filters.append(GeneratedContentRecord.completed_at >= query.completed_from)
    if query.completed_to is not None:
        filters.append(GeneratedContentRecord.completed_at <= query.completed_to)
    if query.has_publication is not None:
        condition = exists(
            select(1).where(PublicationRecord.content_id == GeneratedContentRecord.id)
        )
        filters.append(condition if query.has_publication else ~condition)
    if query.failed_only:
        filters.append(GeneratedContentRecord.generation_status == "failed")
    return tuple(filters)


def _publication_filters(query: PublicationQuery) -> tuple[ColumnElement[bool], ...]:
    filters: list[ColumnElement[bool]] = []
    if query.event_id is not None:
        filters.append(PublicationRecord.event_id == query.event_id)
    if query.content_id is not None:
        filters.append(PublicationRecord.content_id == query.content_id)
    if query.channel is not None:
        filters.append(PublicationRecord.channel == query.channel)
    if query.status is not None:
        filters.append(PublicationRecord.publication_status == query.status)
    if query.retryable is True:
        filters.append(
            and_(
                PublicationRecord.publication_status == "failed",
                PublicationRecord.next_retry_at.is_not(None),
            )
        )
    elif query.retryable is False:
        filters.append(
            or_(
                PublicationRecord.publication_status != "failed",
                PublicationRecord.next_retry_at.is_(None),
            )
        )
    if query.permanent_failure is True:
        filters.append(
            and_(
                PublicationRecord.publication_status == "failed",
                PublicationRecord.next_retry_at.is_(None),
            )
        )
    elif query.permanent_failure is False:
        filters.append(
            or_(
                PublicationRecord.publication_status != "failed",
                PublicationRecord.next_retry_at.is_not(None),
            )
        )
    if query.ambiguous_only:
        filters.append(PublicationRecord.publication_status == "ambiguous")
    if query.scheduled_from is not None:
        filters.append(PublicationRecord.scheduled_at >= query.scheduled_from)
    if query.scheduled_to is not None:
        filters.append(PublicationRecord.scheduled_at <= query.scheduled_to)
    if query.published_from is not None:
        filters.append(PublicationRecord.published_at >= query.published_from)
    if query.published_to is not None:
        filters.append(PublicationRecord.published_at <= query.published_to)
    if query.min_attempts is not None:
        filters.append(PublicationRecord.attempt_count >= query.min_attempts)
    if query.max_attempts is not None:
        filters.append(PublicationRecord.attempt_count <= query.max_attempts)
    return tuple(filters)


def _event_failure_exists() -> ColumnElement[bool]:
    return or_(
        MarketEventRecord.scoring_status == "failed",
        exists(
            select(1).where(
                GeneratedContentRecord.event_id == MarketEventRecord.id,
                GeneratedContentRecord.generation_status == "failed",
            )
        ),
        exists(
            select(1).where(
                PublicationRecord.event_id == MarketEventRecord.id,
                PublicationRecord.publication_status.in_(("failed", "ambiguous")),
            )
        ),
    )


def _like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _count_for_event(model: Any) -> Any:
    return (
        select(func.count(model.id))
        .where(model.event_id == MarketEventRecord.id)
        .correlate(MarketEventRecord)
        .scalar_subquery()
    )


def _statuses_for_event(column: Any, model: Any) -> Any:
    return (
        select(func.array_agg(column))
        .where(model.event_id == MarketEventRecord.id)
        .correlate(MarketEventRecord)
        .scalar_subquery()
    )


def _count_for_content() -> Any:
    return (
        select(func.count(PublicationRecord.id))
        .where(PublicationRecord.content_id == GeneratedContentRecord.id)
        .correlate(GeneratedContentRecord)
        .scalar_subquery()
    )


def _statuses_for_content(column: Any) -> Any:
    return (
        select(func.array_agg(column))
        .where(PublicationRecord.content_id == GeneratedContentRecord.id)
        .correlate(GeneratedContentRecord)
        .scalar_subquery()
    )


def _event_sort_column(sort: str) -> Any:
    if sort == "created_at":
        return MarketEventRecord.created_at
    return MarketEventRecord.detected_at


def _content_sort_column(sort: str) -> Any:
    if sort == "updated_at":
        return GeneratedContentRecord.updated_at
    return GeneratedContentRecord.created_at


def _keyset_after(
    timestamp_column: Any,
    id_column: Any,
    cursor: CursorPosition,
    direction: str,
) -> ColumnElement[bool]:
    if direction == "asc":
        return or_(
            timestamp_column > cursor.timestamp,
            and_(
                timestamp_column == cursor.timestamp,
                id_column > cursor.item_id,
            ),
        )
    return or_(
        timestamp_column < cursor.timestamp,
        and_(
            timestamp_column == cursor.timestamp,
            id_column < cursor.item_id,
        ),
    )


def _window_filter(column: Any, window: DashboardWindow) -> ColumnElement[bool]:
    return and_(column >= window.starts_at, column < window.ends_at)


def _event_from_row(row: Any) -> EventRead:
    record = row[0]
    previous = row[1]
    current = row[2]
    return EventRead(
        id=record.id,
        identity_key=record.identity_key,
        identity_version=record.identity_version,
        event_type=record.event_type,
        marketplace=record.marketplace,
        external_id=record.external_id,
        canonical_product_id=record.canonical_product_id,
        payload=PriceDropPayloadRead(
            payload_type=record.event_type,
            version=record.identity_version,
            title=record.title,
            url=record.url,
            old_price=record.old_price,
            new_price=record.new_price,
            currency=record.currency,
            absolute_difference=record.old_price - record.new_price,
            percentage=record.percentage,
            previous_snapshot=_snapshot_from_record(previous),
            current_snapshot=_snapshot_from_record(current),
        ),
        occurred_at=record.occurred_at,
        detected_at=record.detected_at,
        created_at=record.created_at,
        disposition=record.disposition,
        scoring_status=record.scoring_status,
        score=record.score,
        scoring_attempt_count=record.scoring_attempt_count,
        next_retry_at=record.next_retry_at,
        error_code=safe_error(record.last_error_code, record.last_error_summary)[0],
        error_summary=safe_error(record.last_error_code, record.last_error_summary)[1],
        version=record.version,
        content_summary=_summary(row[3], row[4]),
        publication_summary=_summary(row[5], row[6]),
    )


def _content_from_row(row: Any) -> ContentRead:
    record = row[0]
    error_code, error_summary = safe_error(
        record.last_error_code,
        record.last_error_summary,
    )
    return ContentRead(
        id=record.id,
        event_id=record.event_id,
        parent_content_id=record.parent_content_id,
        content_type=record.content_type,
        language=record.language,
        origin=record.origin,
        provider=safe_label(record.provider),
        model=safe_label(record.model, maximum=255),
        prompt_version=record.prompt_version,
        content_text=record.content_text,
        generation_status=record.generation_status,
        review_status=record.review_status,
        attempt_number=record.attempt_number,
        content_checksum=record.content_checksum,
        next_retry_at=record.next_retry_at,
        error_code=error_code,
        error_summary=error_summary,
        created_at=record.created_at,
        updated_at=record.updated_at,
        completed_at=record.completed_at,
        version=record.version,
        publication_summary=_summary(row[1], row[2]),
    )


def _publication_from_record(record: PublicationRecord) -> PublicationRead:
    error_code, error_summary = safe_error(
        record.last_error_code,
        record.last_error_summary,
    )
    return PublicationRead(
        id=record.id,
        event_id=record.event_id,
        content_id=record.content_id,
        channel=record.channel,
        destination_reference=destination_reference(record.destination_key),
        status=record.publication_status,
        attempt_count=record.attempt_count,
        external_message_id=record.external_message_id,
        scheduled_at=record.scheduled_at,
        next_retry_at=record.next_retry_at,
        published_at=record.published_at,
        error_code=error_code,
        error_summary=error_summary,
        created_at=record.created_at,
        updated_at=record.updated_at,
        version=record.version,
    )


def _snapshot_from_record(record: PriceSnapshotRecord) -> SnapshotRead:
    return SnapshotRead(
        marketplace=record.marketplace,
        external_id=record.external_id,
        collected_at=record.collected_at,
        price=record.price,
        currency=record.currency,
    )


def _summary(count: int | None, statuses: Sequence[str] | None) -> RelatedSummary:
    return RelatedSummary(
        count=int(count or 0),
        statuses=tuple(sorted(set(statuses or ()))),
    )
