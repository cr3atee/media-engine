from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database.metadata import get_metadata
from app.delivery.contracts import DeliveryMessage, DeliveryOutcome, DeliveryResult
from app.domain.generated_content import (
    CreateContentAttempt,
    calculate_content_checksum,
)
from app.domain.lifecycle import ContentReviewStatus, PublicationStatus
from app.domain.market_events import MarketEventCandidate, SnapshotIdentity
from app.domain.price_snapshot import PriceSnapshot
from app.domain.publications import CreatePublication, Publication
from app.repositories.provider import RepositoryProvider, create_postgres_provider
from app.services.publication_delivery import (
    PublicationDeliveryPolicy,
    PublicationDeliveryService,
)
from app.services.repository_scope import RepositoryScopeFactory
from tests.repositories.contracts.factories import NOW, make_event, run_async, uuid_for

DATABASE_URL = os.getenv("EPIC14_DATABASE_URL")
_ISOLATED_DATABASE = DATABASE_URL is not None and (
    make_url(DATABASE_URL).database or ""
).startswith("epic14_")
_SKIP_REASON = (
    "EPIC14_DATABASE_URL must target an isolated epic14_* PostgreSQL database"
)
_ENGINE: AsyncEngine | None = (
    create_async_engine(DATABASE_URL)
    if DATABASE_URL is not None and _ISOLATED_DATABASE
    else None
)
_SESSION_FACTORY: async_sessionmaker[AsyncSession] | None = (
    async_sessionmaker(_ENGINE, expire_on_commit=False) if _ENGINE is not None else None
)

pytestmark = pytest.mark.skipif(not _ISOLATED_DATABASE, reason=_SKIP_REASON)

DESTINATION_ID = "-1001234567890"


class TrackedPostgresScopes:
    """Create short PostgreSQL scopes and expose active transaction state."""

    def __init__(self) -> None:
        self.active = 0
        self.entries = 0

    def factory(self) -> RepositoryScopeFactory:
        """Return a repository scope factory backed by isolated PostgreSQL."""
        return self.scope

    @asynccontextmanager
    async def scope(self) -> AsyncIterator[RepositoryProvider]:
        self.entries += 1
        async with _session_factory()() as session, session.begin():
            self.active += 1
            try:
                yield create_postgres_provider(session)
            finally:
                self.active -= 1


class RecordingAdapter:
    """Return one successful result and record active scope state."""

    def __init__(self, scopes: TrackedPostgresScopes) -> None:
        self.scopes = scopes
        self.messages: list[DeliveryMessage] = []
        self.scope_states: list[int] = []

    async def send(self, message: DeliveryMessage) -> DeliveryResult:
        """Record delivery boundary and return a confirmed success."""
        self.messages.append(message)
        self.scope_states.append(self.scopes.active)
        return DeliveryResult(
            outcome=DeliveryOutcome.SUCCESS,
            destination_id=DESTINATION_ID,
            external_message_id="postgres-message-1",
        )


def test_postgres_delivery_success_survives_fresh_session() -> None:
    async def scenario() -> None:
        await _reset_database()
        publication_id = await _seed_publication()
        scopes = TrackedPostgresScopes()
        adapter = RecordingAdapter(scopes)
        service = PublicationDeliveryService(
            repository_scope_factory=scopes.factory(),
            adapter=adapter,
            policy=PublicationDeliveryPolicy(
                allowed_destination_ids=frozenset({DESTINATION_ID})
            ),
            clock=lambda: NOW + timedelta(minutes=20),
        )

        result = await service.process_batch(
            worker_id="postgres-delivery-worker",
            limit=1,
        )
        stored = await _load_publication(publication_id)

        assert result.published == 1
        assert adapter.scope_states == [0]
        assert stored is not None
        assert stored.status is PublicationStatus.PUBLISHED
        assert stored.external_message_id == "postgres-message-1"

    run_async(scenario())


async def _reset_database() -> None:
    async with _engine().begin() as connection:
        await connection.run_sync(get_metadata().drop_all)
        await connection.run_sync(get_metadata().create_all)


async def _seed_publication() -> UUID:
    event = make_event(event_id=uuid_for(71_001))
    content_id = uuid_for(72_001)
    publication_id = uuid_for(73_001)
    async with _session_factory()() as session, session.begin():
        provider = create_postgres_provider(session)
        await provider.price_history.add(_snapshot(event.previous_snapshot))
        await provider.price_history.add(_snapshot(event.current_snapshot))
        await provider.events.add_idempotently(MarketEventCandidate(event=event))
        await provider.generated_contents.create_attempt(
            CreateContentAttempt(
                id=content_id,
                event_id=event.id,
                content_type="telegram_post",
                language="ru",
                prompt_version="price_drop_v1",
                attempt_number=1,
                provider="fake",
                model="deterministic",
                created_at=NOW + timedelta(minutes=10),
            )
        )
        claimed = (
            await provider.generated_contents.claim_pending(
                NOW + timedelta(minutes=10),
                "content-worker",
                NOW + timedelta(minutes=11),
                1,
            )
        )[0]
        text = "PostgreSQL generated publication"
        await provider.generated_contents.complete_attempt(
            content_id,
            claimed.claim.token,
            claimed.content.version,
            text,
            calculate_content_checksum(text),
            NOW + timedelta(minutes=10, seconds=1),
        )
        completed = await provider.generated_contents.get_by_id(content_id)
        assert completed is not None
        await provider.generated_contents.set_review_status(
            content_id,
            ContentReviewStatus.APPROVED,
            NOW + timedelta(minutes=10, seconds=2),
            completed.version,
        )
        await provider.publications.create_idempotently(
            CreatePublication(
                id=publication_id,
                event_id=event.id,
                content_id=content_id,
                channel="telegram",
                destination_key=DESTINATION_ID,
                created_at=NOW + timedelta(minutes=11),
            )
        )
    return publication_id


async def _load_publication(publication_id: UUID) -> Publication | None:
    async with _session_factory()() as session:
        provider = create_postgres_provider(session)
        return await provider.publications.get_by_id(publication_id)


def _snapshot(identity: SnapshotIdentity) -> PriceSnapshot:
    return PriceSnapshot(
        marketplace=identity.marketplace,
        external_id=identity.external_id,
        price=identity.price,
        currency=identity.currency,
        collected_at=identity.collected_at,
    )


def _engine() -> AsyncEngine:
    assert _ENGINE is not None
    return _ENGINE


def _session_factory() -> async_sessionmaker[AsyncSession]:
    assert _SESSION_FACTORY is not None
    return _SESSION_FACTORY
