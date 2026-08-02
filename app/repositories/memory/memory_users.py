from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from app.domain.tenancy import User, normalize_email, utc_now
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.users import UserRepository


class MemoryUserRepository(UserRepository):
    """Deterministic in-memory repository for user identities."""

    def __init__(self) -> None:
        """Initialize isolated user storage."""
        self._users_by_id: dict[UUID, User] = {}
        self._user_ids_by_email: dict[str, UUID] = {}

    async def create(self, user: User) -> User:
        """Persist one user while enforcing normalized email uniqueness."""
        email = normalize_email(user.email)
        existing_id = self._user_ids_by_email.get(email)
        if existing_id is not None and existing_id != user.id:
            msg = f"User email already exists: {email}."
            raise RepositoryIdentityConflictError(msg)
        if user.id in self._users_by_id:
            msg = f"User ID already exists: {user.id}."
            raise RepositoryIdentityConflictError(msg)
        self._users_by_id[user.id] = user
        self._user_ids_by_email[email] = user.id
        return user

    async def get_by_id(self, user_id: UUID) -> User | None:
        """Return one user by technical identifier."""
        return self._users_by_id.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        """Return one user by normalized email identity."""
        user_id = self._user_ids_by_email.get(normalize_email(email))
        return self._users_by_id.get(user_id) if user_id is not None else None

    async def set_enabled(
        self,
        user_id: UUID,
        enabled: bool,
        expected_version: int,
    ) -> User | None:
        """Update enabled state when the expected version matches."""
        user = self._users_by_id.get(user_id)
        if user is None or user.version != expected_version:
            return None
        updated = replace(
            user,
            enabled=enabled,
            updated_at=utc_now(),
            version=user.version + 1,
        )
        self._users_by_id[user_id] = updated
        return updated
