from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from app.domain.product_access import LastProductAdminError, ProductRole
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
        if user.product_role is not ProductRole.USER:
            raise ValueError("New users must start with the user product role.")
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
        if not enabled:
            self._guard_last_admin(user)
        updated = replace(
            user,
            enabled=enabled,
            updated_at=utc_now(),
            version=user.version + 1,
        )
        self._users_by_id[user_id] = updated
        return updated

    async def lock_role_changes(self) -> None:
        """The enclosing memory repository scope serializes all commands."""

    async def list_product_admins(self) -> tuple[User, ...]:
        """Return explicit admin grants without inferring workspace privileges."""
        return tuple(
            user
            for user in self._users_by_id.values()
            if user.product_role is ProductRole.ADMIN
        )

    async def set_product_role(
        self, user_id: UUID, role: ProductRole, expected_version: int
    ) -> User | None:
        """Apply an optimistic update without removing the final active admin."""
        user = self._users_by_id.get(user_id)
        if user is None or user.version != expected_version:
            return None
        if role is not ProductRole.ADMIN:
            self._guard_last_admin(user)
        updated = replace(
            user, product_role=role, version=user.version + 1, updated_at=utc_now()
        )
        self._users_by_id[user_id] = updated
        return updated

    def _guard_last_admin(self, user: User) -> None:
        if (
            user.enabled
            and user.product_role is ProductRole.ADMIN
            and not any(
                other.id != user.id
                and other.enabled
                and other.product_role is ProductRole.ADMIN
                for other in self._users_by_id.values()
            )
        ):
            raise LastProductAdminError(
                "The last enabled product admin must remain active."
            )
