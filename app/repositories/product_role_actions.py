"""Append-only role audit contract; updates and deletion are not exposed."""

from abc import abstractmethod
from uuid import UUID

from app.domain.product_access import ProductRoleAction
from app.repositories.base import BaseRepository


class ProductRoleActionRepository(BaseRepository):
    """Store accepted commands within the same transaction as role changes."""

    @abstractmethod
    async def append(self, action: ProductRoleAction) -> None:
        """Append a unique actor/key command, never overwrite history."""

    @abstractmethod
    async def get_replay(
        self, actor_key: str, idempotency_key: str
    ) -> ProductRoleAction | None:
        """Return one actor-scoped idempotent result."""

    @abstractmethod
    async def list_for_user(
        self, user_id: UUID, limit: int = 100
    ) -> tuple[ProductRoleAction, ...]:
        """Return newest actions first, with a bounded limit."""
