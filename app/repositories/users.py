from __future__ import annotations

from abc import abstractmethod
from uuid import UUID

from app.domain.product_access import ProductRole
from app.domain.tenancy import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository):
    """Abstract storage contract for durable user identities."""

    @abstractmethod
    async def create(self, user: User) -> User:
        """Persist a new user identity."""

    @abstractmethod
    async def get_by_id(self, user_id: UUID) -> User | None:
        """Return one user by technical identifier."""

    @abstractmethod
    async def get_by_email(self, email: str) -> User | None:
        """Return one user by normalized email."""

    @abstractmethod
    async def set_enabled(
        self,
        user_id: UUID,
        enabled: bool,
        expected_version: int,
    ) -> User | None:
        """Update enabled state using optimistic version guarding."""

    @abstractmethod
    async def lock_role_changes(self) -> None:
        """Serialize role and enabled-state writes until the enclosing scope ends."""

    @abstractmethod
    async def list_product_admins(self) -> tuple[User, ...]:
        """Return explicitly assigned admins, including disabled accounts."""

    @abstractmethod
    async def set_product_role(
        self, user_id: UUID, role: ProductRole, expected_version: int
    ) -> User | None:
        """Set a role with version and last-enabled-admin protection."""
