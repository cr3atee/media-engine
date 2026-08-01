from __future__ import annotations

import asyncio
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
from sqlalchemy.pool import NullPool

from app.database.metadata import get_metadata
from app.domain.admin_actions import AdminAction, AdminResourceType
from app.domain.generated_content import (
    GeneratedContentAttempt,
    calculate_content_checksum,
)
from app.domain.lifecycle import ContentReviewStatus
from app.domain.market_events import MarketEventCandidate, SnapshotIdentity
from app.domain.price_snapshot import PriceSnapshot
from app.repositories.postgres import PostgresAdminActionRepository
from app.repositories.provider import RepositoryProvider, create_postgres_provider
from app.services.admin_mutations import (
    AdminCommandContext,
    AdminMutationService,
    ContentReviewCommand,
)
from app.services.repository_scope import RepositoryScopeFactory
from tests.repositories.contracts.factories import (
    NOW,
    SequentialUuidFactory,
    make_content_command,
    make_event,
    run_async,
    uuid_for,
)

DATABASE_URL = os.getenv("EPIC15_DATABASE_URL")
_ISOLATED_DATABASE = DATABASE_URL is not None and (
    make_url(DATABASE_URL).database or ""
).startswith("epic15_")
_ENGINE: AsyncEngine | None = (
    create_async_engine(DATABASE_URL, poolclass=NullPool)
    if DATABASE_URL is not None and _ISOLATED_DATABASE
    else None
)
_SESSION_FACTORY: async_sessionmaker[AsyncSession] | None = (
    async_sessionmaker(_ENGINE, expire_on_commit=False) if _ENGINE is not None else None
)

pytestmark = pytest.mark.skipif(
    not _ISOLATED_DATABASE,
    reason="EPIC15_DATABASE_URL must target an isolated epic15_* PostgreSQL database",
)


class FailingPostgresAdminActionRepository(PostgresAdminActionRepository):
    """Fail audit insertion to prove transition rollback."""

    async def append(self, action: AdminAction) -> AdminAction:
        """Raise after the caller has already applied the resource transition."""
        del action
        msg = "controlled postgres audit failure"
        raise RuntimeError(msg)


def test_postgres_admin_mutation_commit_replay_and_fresh_session() -> None:
    async def scenario() -> None:
        await _reset_database()
        content_id, version = await _seed_generated_content(number=1)
        service = _service(_postgres_scope_factory())
        context = _context("postgres-approve-1")

        result = await service.approve(
            ContentReviewCommand(content_id=content_id, expected_version=version),
            context,
        )
        replay = await service.approve(
            ContentReviewCommand(content_id=content_id, expected_version=version),
            context,
        )
        stored, actions = await _load_content_and_actions(content_id)

        assert result.replayed is False
        assert replay.replayed is True
        assert replay.action_id == result.action_id
        assert stored is not None
        assert stored.review_status is ContentReviewStatus.APPROVED
        assert stored.version == version + 1
        assert len(actions) == 1
        assert actions[0].resulting_version == stored.version

    run_async(scenario())


def test_postgres_concurrent_duplicate_idempotency_creates_one_action() -> None:
    async def scenario() -> None:
        await _reset_database()
        content_id, version = await _seed_generated_content(number=2)
        service = _service(_postgres_scope_factory())
        command = ContentReviewCommand(
            content_id=content_id,
            expected_version=version,
        )
        context = _context("postgres-concurrent-approve")

        first, second = await asyncio.gather(
            service.approve(command, context),
            service.approve(command, context),
        )
        stored, actions = await _load_content_and_actions(content_id)

        assert first.action_id == second.action_id
        assert {first.replayed, second.replayed} == {False, True}
        assert stored is not None
        assert stored.version == version + 1
        assert len(actions) == 1

    run_async(scenario())


def test_postgres_audit_failure_rolls_back_state_change() -> None:
    async def scenario() -> None:
        await _reset_database()
        content_id, version = await _seed_generated_content(number=3)
        service = _service(_failing_scope_factory())

        with pytest.raises(RuntimeError, match="controlled postgres audit failure"):
            await service.approve(
                ContentReviewCommand(
                    content_id=content_id,
                    expected_version=version,
                ),
                _context("postgres-rollback"),
            )
        stored, actions = await _load_content_and_actions(content_id)

        assert stored is not None
        assert stored.review_status is ContentReviewStatus.PENDING
        assert stored.version == version
        assert actions == ()

    run_async(scenario())


def _service(scope_factory: RepositoryScopeFactory) -> AdminMutationService:
    return AdminMutationService(
        scope_factory,
        maximum_publication_attempts=5,
        clock=lambda: NOW + timedelta(hours=1),
        action_id_factory=SequentialUuidFactory(95_000),
    )


def _context(idempotency_key: str) -> AdminCommandContext:
    return AdminCommandContext(
        actor_id="postgres-admin",
        request_id="postgres-request-1",
        idempotency_key=idempotency_key,
    )


async def _seed_generated_content(*, number: int) -> tuple[UUID, int]:
    assert _SESSION_FACTORY is not None
    event = make_event(number=number, event_id=uuid_for(110_000 + number))
    command = make_content_command(
        number=number,
        event_id=event.id,
        content_id=uuid_for(111_000 + number),
    )
    async with _SESSION_FACTORY() as session, session.begin():
        provider = create_postgres_provider(session)
        await provider.price_history.add(_snapshot(event.previous_snapshot))
        await provider.price_history.add(_snapshot(event.current_snapshot))
        await provider.events.add_idempotently(MarketEventCandidate(event=event))
        await provider.generated_contents.create_attempt(command)
        claimed = (
            await provider.generated_contents.claim_pending(
                NOW + timedelta(minutes=10),
                "content-worker",
                NOW + timedelta(minutes=11),
                1,
            )
        )[0]
        text = f"Generated content {number}"
        await provider.generated_contents.complete_attempt(
            command.id,
            claimed.claim.token,
            claimed.content.version,
            text,
            calculate_content_checksum(text),
            NOW + timedelta(minutes=10, seconds=1),
        )
        stored = await provider.generated_contents.get_by_id(command.id)
        assert stored is not None
        return stored.id, stored.version


async def _load_content_and_actions(
    content_id: UUID,
) -> tuple[GeneratedContentAttempt | None, tuple[AdminAction, ...]]:
    assert _SESSION_FACTORY is not None
    async with _SESSION_FACTORY() as session:
        provider = create_postgres_provider(session)
        stored = await provider.generated_contents.get_by_id(content_id)
        actions = await provider.admin_actions.list_for_resource(
            AdminResourceType.CONTENT,
            content_id,
        )
        return stored, tuple(actions)


def _snapshot(identity: SnapshotIdentity) -> PriceSnapshot:
    return PriceSnapshot(
        marketplace=identity.marketplace,
        external_id=identity.external_id,
        price=identity.price,
        currency=identity.currency,
        collected_at=identity.collected_at,
    )


def _postgres_scope_factory() -> RepositoryScopeFactory:
    @asynccontextmanager
    async def scope() -> AsyncIterator[RepositoryProvider]:
        assert _SESSION_FACTORY is not None
        async with _SESSION_FACTORY() as session, session.begin():
            yield create_postgres_provider(session)

    return scope


def _failing_scope_factory() -> RepositoryScopeFactory:
    @asynccontextmanager
    async def scope() -> AsyncIterator[RepositoryProvider]:
        assert _SESSION_FACTORY is not None
        async with _SESSION_FACTORY() as session, session.begin():
            provider = create_postgres_provider(session)
            provider.admin_actions = FailingPostgresAdminActionRepository(session)
            yield provider

    return scope


async def _reset_database() -> None:
    assert _ENGINE is not None
    async with _ENGINE.begin() as connection:
        await connection.run_sync(get_metadata().drop_all)
        await connection.run_sync(get_metadata().create_all)


def teardown_module() -> None:
    if _ENGINE is not None:
        run_async(_ENGINE.dispose())
