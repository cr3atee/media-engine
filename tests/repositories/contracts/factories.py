from __future__ import annotations

import asyncio
import atexit
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.domain.generated_content import CreateContentAttempt
from app.domain.market_events import (
    PriceDropMarketEvent,
    PriceDropPayload,
    SnapshotIdentity,
    create_price_drop_market_event,
)
from app.domain.publications import CreatePublication

NOW = datetime(2026, 7, 29, 9, 0, tzinfo=UTC)
_ASYNC_RUNNER = asyncio.Runner()
atexit.register(_ASYNC_RUNNER.close)


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run async repository contracts without an async Pytest plugin."""
    return _ASYNC_RUNNER.run(awaitable)


def uuid_for(value: int) -> UUID:
    """Build a stable UUID from a small test integer."""
    return UUID(int=value)


class SequentialUuidFactory:
    """Return deterministic, unique claim tokens for one repository instance."""

    def __init__(self, start: int = 10_000) -> None:
        self._next = start

    def __call__(self) -> UUID:
        token = uuid_for(self._next)
        self._next += 1
        return token


def make_event(
    *,
    number: int = 1,
    event_id: UUID | None = None,
    external_id: str | None = None,
    occurred_at: datetime | None = None,
    created_at: datetime | None = None,
    title: str | None = "Minecraft Premium",
) -> PriceDropMarketEvent:
    """Create one deterministic price-drop event for repository contracts."""
    occurred_at = occurred_at or NOW + timedelta(minutes=number)
    detected_at = occurred_at + timedelta(seconds=1)
    previous = SnapshotIdentity(
        marketplace="ggsel",
        external_id=external_id or f"offer-{number}",
        collected_at=occurred_at - timedelta(minutes=1),
        price=Decimal("1000.00"),
        currency="RUB",
    )
    current = SnapshotIdentity(
        marketplace="ggsel",
        external_id=external_id or f"offer-{number}",
        collected_at=occurred_at,
        price=Decimal("800.00"),
        currency="RUB",
    )
    payload = PriceDropPayload(
        title=title,
        url=f"https://example.com/offers/{external_id or number}",
        old_price=previous.price,
        new_price=current.price,
        currency="RUB",
        absolute_difference=Decimal("200.00"),
        percentage=Decimal("20.0"),
        previous_snapshot=previous,
        current_snapshot=current,
    )
    return create_price_drop_market_event(
        payload=payload,
        detected_at=detected_at,
        event_id=event_id or uuid_for(100 + number),
        created_at=created_at or detected_at + timedelta(seconds=1),
    )


def make_content_command(
    *,
    number: int = 1,
    event_id: UUID | None = None,
    content_id: UUID | None = None,
    attempt_number: int | None = None,
    content_type: str = "telegram_post",
    language: str = "ru",
    prompt_version: str = "price_drop_v1",
    parent_content_id: UUID | None = None,
    provider: str | None = "fake",
    model: str | None = "deterministic",
    created_at: datetime | None = None,
) -> CreateContentAttempt:
    """Create one deterministic AI content-attempt command."""
    return CreateContentAttempt(
        id=content_id or uuid_for(200 + number),
        event_id=event_id or uuid_for(101),
        content_type=content_type,
        language=language,
        prompt_version=prompt_version,
        attempt_number=attempt_number or number,
        parent_content_id=parent_content_id,
        provider=provider,
        model=model,
        created_at=created_at or NOW + timedelta(minutes=number),
    )


def make_publication_command(
    *,
    number: int = 1,
    event_id: UUID | None = None,
    content_id: UUID | None = None,
    publication_id: UUID | None = None,
    channel: str = "preview",
    destination_key: str = "review-channel",
    scheduled_at: datetime | None = None,
    created_at: datetime | None = None,
) -> CreatePublication:
    """Create one deterministic channel-neutral publication command."""
    return CreatePublication(
        id=publication_id or uuid_for(300 + number),
        event_id=event_id or uuid_for(101),
        content_id=content_id or uuid_for(201),
        channel=channel,
        destination_key=destination_key,
        scheduled_at=scheduled_at,
        created_at=created_at or NOW + timedelta(minutes=number),
    )
