from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.admin_actions import (
    AdminAction,
    AdminActionType,
    AdminResourceType,
)
from app.models.admin_action_record import AdminActionRecord
from app.repositories.admin_actions import AdminActionRepository
from app.repositories.base import RepositoryIdentityConflictError


class PostgresAdminActionRepository(AdminActionRepository):
    """PostgreSQL append-only persistence for administrative audit actions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def acquire_idempotency_lock(self, idempotency_key: str) -> None:
        """Acquire a transaction-scoped advisory lock for one command key."""
        if not idempotency_key.strip():
            msg = "Idempotency key must not be empty."
            raise ValueError(msg)
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": idempotency_key},
        )

    async def append(self, action: AdminAction) -> AdminAction:
        """Append one immutable action inside the caller-owned transaction."""
        existing = await self.get_by_idempotency_key(action.idempotency_key)
        if existing is not None:
            if existing.request_fingerprint != action.request_fingerprint:
                msg = "Idempotency key is already bound to another admin command."
                raise RepositoryIdentityConflictError(msg)
            return existing
        existing_by_id = await self.get_by_id(action.id)
        if existing_by_id is not None:
            msg = "Admin action ID is already in use."
            raise RepositoryIdentityConflictError(msg)
        self._session.add(_to_record(action))
        await self._session.flush()
        return action

    async def get_by_id(self, action_id: UUID) -> AdminAction | None:
        """Return one immutable action by identifier."""
        record = await self._session.get(AdminActionRecord, action_id)
        return _to_domain(record) if record is not None else None

    async def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> AdminAction | None:
        """Return an accepted action by idempotency key."""
        result = await self._session.execute(
            select(AdminActionRecord).where(
                AdminActionRecord.idempotency_key == idempotency_key
            )
        )
        record = result.scalar_one_or_none()
        return _to_domain(record) if record is not None else None

    async def list_for_resource(
        self,
        resource_type: AdminResourceType,
        resource_id: UUID,
    ) -> Sequence[AdminAction]:
        """Return a resource history in deterministic chronological order."""
        result = await self._session.execute(
            select(AdminActionRecord)
            .where(
                AdminActionRecord.resource_type == resource_type.value,
                AdminActionRecord.resource_id == resource_id,
            )
            .order_by(AdminActionRecord.created_at, AdminActionRecord.id)
        )
        return tuple(_to_domain(record) for record in result.scalars())


def _to_record(action: AdminAction) -> AdminActionRecord:
    return AdminActionRecord(
        id=action.id,
        action=action.action.value,
        resource_type=action.resource_type.value,
        resource_id=action.resource_id,
        previous_state=action.previous_state,
        resulting_state=action.resulting_state,
        reason=action.reason,
        actor_id=action.actor_id,
        request_id=action.request_id,
        idempotency_key=action.idempotency_key,
        request_fingerprint=action.request_fingerprint,
        expected_version=action.expected_version,
        resulting_version=action.resulting_version,
        created_at=action.created_at,
        action_metadata=dict(action.metadata),
    )


def _to_domain(record: AdminActionRecord) -> AdminAction:
    return AdminAction(
        id=record.id,
        action=AdminActionType(record.action),
        resource_type=AdminResourceType(record.resource_type),
        resource_id=record.resource_id,
        previous_state=record.previous_state,
        resulting_state=record.resulting_state,
        reason=record.reason,
        actor_id=record.actor_id,
        request_id=record.request_id,
        idempotency_key=record.idempotency_key,
        request_fingerprint=record.request_fingerprint,
        expected_version=record.expected_version,
        resulting_version=record.resulting_version,
        created_at=record.created_at,
        metadata=tuple(sorted(record.action_metadata.items())),
    )
