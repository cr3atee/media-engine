from __future__ import annotations

import os
from collections.abc import Callable
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
from app.domain.admin_actions import (
    AdminAction,
    AdminActionType,
    AdminResourceType,
    build_admin_request_fingerprint,
)
from app.repositories.admin_actions import AdminActionRepository
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.memory import MemoryAdminActionRepository
from app.repositories.provider import create_postgres_provider
from tests.repositories.contracts.factories import NOW, run_async, uuid_for

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


def test_memory_admin_action_repository_is_append_only_and_idempotent() -> None:
    async def scenario() -> None:
        repository = MemoryAdminActionRepository()
        await _exercise_repository(lambda: repository)

    run_async(scenario())


@pytest.mark.skipif(
    not _ISOLATED_DATABASE,
    reason="EPIC15_DATABASE_URL must target an isolated epic15_* PostgreSQL database",
)
def test_postgres_admin_action_repository_matches_memory_contract() -> None:
    async def scenario() -> None:
        await _reset_database()
        assert _SESSION_FACTORY is not None
        async with _SESSION_FACTORY() as session, session.begin():
            provider = create_postgres_provider(session)
            await _exercise_repository(lambda: provider.admin_actions)

    run_async(scenario())


async def _exercise_repository(
    repository_factory: Callable[[], AdminActionRepository],
) -> None:
    repository = repository_factory()
    first = _action(action_id=uuid_for(91_001), idempotency_key="repo-key-1")
    second = _action(
        action_id=uuid_for(91_002),
        resource_id=first.resource_id,
        idempotency_key="repo-key-2",
        created_offset_seconds=1,
    )

    await repository.acquire_idempotency_lock(first.idempotency_key)
    stored = await repository.append(first)
    replay = await repository.append(
        _action(action_id=uuid_for(91_003), idempotency_key="repo-key-1")
    )
    await repository.append(second)
    by_id = await repository.get_by_id(first.id)
    by_key = await repository.get_by_idempotency_key(first.idempotency_key)
    trail = await repository.list_for_resource(first.resource_type, first.resource_id)

    assert stored == first
    assert replay == first
    assert by_id == first
    assert by_key == first
    assert tuple(action.id for action in trail) == (first.id, second.id)

    with pytest.raises(RepositoryIdentityConflictError):
        await repository.append(
            _action(
                action_id=uuid_for(91_004),
                idempotency_key="repo-key-1",
                reason="different semantics",
            )
        )


def _action(
    *,
    action_id: UUID,
    resource_id: UUID | None = None,
    idempotency_key: str,
    reason: str | None = None,
    created_offset_seconds: int = 0,
) -> AdminAction:
    resource_id = resource_id or uuid_for(99_001)
    fingerprint = build_admin_request_fingerprint(
        actor_id="test-admin",
        action=AdminActionType.APPROVE_CONTENT,
        resource_type=AdminResourceType.CONTENT,
        resource_id=resource_id,
        expected_version=1,
        reason=reason,
    )
    return AdminAction(
        id=action_id,
        action=AdminActionType.APPROVE_CONTENT,
        resource_type=AdminResourceType.CONTENT,
        resource_id=resource_id,
        previous_state="pending",
        resulting_state="approved",
        actor_id="test-admin",
        request_id="request-1",
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
        expected_version=1,
        resulting_version=2,
        created_at=NOW + timedelta(seconds=created_offset_seconds),
        reason=reason,
    )


async def _reset_database() -> None:
    assert _ENGINE is not None
    async with _ENGINE.begin() as connection:
        await connection.run_sync(get_metadata().drop_all)
        await connection.run_sync(get_metadata().create_all)


def teardown_module() -> None:
    if _ENGINE is not None:
        run_async(_ENGINE.dispose())
