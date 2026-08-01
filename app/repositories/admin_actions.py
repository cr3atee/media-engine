from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from uuid import UUID

from app.domain.admin_actions import AdminAction, AdminResourceType
from app.repositories.base import BaseRepository


class AdminActionRepository(BaseRepository):
    """Append-only persistence contract for immutable admin actions."""

    @abstractmethod
    async def acquire_idempotency_lock(self, idempotency_key: str) -> None:
        """Serialize commands sharing one explicit idempotency key."""

    @abstractmethod
    async def append(self, action: AdminAction) -> AdminAction:
        """Append one action, returning an identical existing replay if present."""

    @abstractmethod
    async def get_by_id(self, action_id: UUID) -> AdminAction | None:
        """Return one immutable action by identifier."""

    @abstractmethod
    async def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> AdminAction | None:
        """Return the accepted action associated with an idempotency key."""

    @abstractmethod
    async def list_for_resource(
        self,
        resource_type: AdminResourceType,
        resource_id: UUID,
    ) -> Sequence[AdminAction]:
        """Return a resource audit trail in stable chronological order."""
