from __future__ import annotations

from abc import abstractmethod
from uuid import UUID

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
