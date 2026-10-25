"""Memory role audit participating in the existing rollback-capable scope."""

from uuid import UUID

from app.domain.product_access import ProductRoleAction
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.product_role_actions import ProductRoleActionRepository


class MemoryProductRoleActionRepository(ProductRoleActionRepository):
    """Append-only isolated storage for demos and tests."""

    def __init__(self) -> None:
        self._actions: dict[UUID, ProductRoleAction] = {}

    async def append(self, action: ProductRoleAction) -> None:
        """Record a command once; reject duplicate IDs and replay keys."""
        if action.id in self._actions or await self.get_replay(
            action.actor_key, action.idempotency_key
        ):
            raise RepositoryIdentityConflictError("Role action already exists.")
        self._actions[action.id] = action

    async def get_replay(
        self, actor_key: str, idempotency_key: str
    ) -> ProductRoleAction | None:
        """Find the original accepted command for an actor-scoped key."""
        return next(
            (
                action
                for action in self._actions.values()
                if action.actor_key == actor_key
                and action.idempotency_key == idempotency_key
            ),
            None,
        )

    async def list_for_user(
        self, user_id: UUID, limit: int = 100
    ) -> tuple[ProductRoleAction, ...]:
        """Return a bounded newest-first history for one account."""
        if not 1 <= limit <= 100:
            raise ValueError("Audit limit must be between 1 and 100.")
        return tuple(
            sorted(
                (
                    action
                    for action in self._actions.values()
                    if action.user_id == user_id
                ),
                key=lambda action: (action.created_at, action.id),
                reverse=True,
            )[:limit]
        )
