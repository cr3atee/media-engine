from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from app.domain.admin_actions import AdminAction, AdminResourceType
from app.repositories.admin_actions import AdminActionRepository
from app.repositories.base import RepositoryIdentityConflictError


class MemoryAdminActionRepository(AdminActionRepository):
    """Append-only in-memory storage for administrative audit actions."""

    def __init__(self) -> None:
        self._actions_by_id: dict[UUID, AdminAction] = {}
        self._action_ids_by_key: dict[str, UUID] = {}

    async def acquire_idempotency_lock(self, idempotency_key: str) -> None:
        """Rely on the enclosing transactional memory scope for serialization."""
        if not idempotency_key.strip():
            msg = "Idempotency key must not be empty."
            raise ValueError(msg)

    async def append(self, action: AdminAction) -> AdminAction:
        """Append an immutable action without replacing existing history."""
        existing_id = self._action_ids_by_key.get(action.idempotency_key)
        if existing_id is not None:
            existing = self._actions_by_id[existing_id]
            if existing.request_fingerprint != action.request_fingerprint:
                msg = "Idempotency key is already bound to another admin command."
                raise RepositoryIdentityConflictError(msg)
            return existing
        existing_by_id = self._actions_by_id.get(action.id)
        if existing_by_id is not None:
            msg = "Admin action ID is already in use."
            raise RepositoryIdentityConflictError(msg)
        self._actions_by_id[action.id] = action
        self._action_ids_by_key[action.idempotency_key] = action.id
        return action

    async def get_by_id(self, action_id: UUID) -> AdminAction | None:
        """Return one action by identifier."""
        return self._actions_by_id.get(action_id)

    async def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> AdminAction | None:
        """Return one action by command idempotency key."""
        action_id = self._action_ids_by_key.get(idempotency_key)
        return self._actions_by_id.get(action_id) if action_id is not None else None

    async def list_for_resource(
        self,
        resource_type: AdminResourceType,
        resource_id: UUID,
    ) -> Sequence[AdminAction]:
        """Return a deterministic append-only resource history."""
        return tuple(
            sorted(
                (
                    action
                    for action in self._actions_by_id.values()
                    if action.resource_type is resource_type
                    and action.resource_id == resource_id
                ),
                key=lambda action: (action.created_at, action.id.hex),
            )
        )
