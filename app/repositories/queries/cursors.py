from __future__ import annotations

from app.repositories.queries.models import (
    ContentRead,
    CursorPosition,
    EventRead,
    PageRequest,
    PublicationRead,
)


def event_cursor(item: EventRead, page: PageRequest) -> CursorPosition:
    """Build the next cursor for an event page."""
    timestamp = item.created_at if page.sort == "created_at" else item.detected_at
    return CursorPosition(
        resource="events",
        sort=page.sort,
        direction=page.direction,
        timestamp=timestamp,
        item_id=item.id,
        filter_hash=page.filter_hash,
    )


def content_cursor(item: ContentRead, page: PageRequest) -> CursorPosition:
    """Build the next cursor for a content page."""
    timestamp = item.updated_at if page.sort == "updated_at" else item.created_at
    return CursorPosition(
        resource="content",
        sort=page.sort,
        direction=page.direction,
        timestamp=timestamp,
        item_id=item.id,
        filter_hash=page.filter_hash,
    )


def publication_cursor(
    item: PublicationRead,
    page: PageRequest,
) -> CursorPosition:
    """Build the next cursor for a publication page."""
    return CursorPosition(
        resource="publications",
        sort="created_at",
        direction=page.direction,
        timestamp=item.created_at,
        item_id=item.id,
        filter_hash=page.filter_hash,
    )
