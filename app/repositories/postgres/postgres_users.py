from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.tenancy import User, normalize_email, utc_now
from app.models.user_record import UserRecord
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.users import UserRepository


class PostgresUserRepository(UserRepository):
    """PostgreSQL-backed repository for durable user identities."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a caller-owned session and transaction."""
        self._session = session

    async def create(self, user: User) -> User:
        """Persist one user while enforcing normalized email uniqueness."""
        if await self.get_by_id(user.id) is not None:
            msg = f"User ID already exists: {user.id}."
            raise RepositoryIdentityConflictError(msg)
        if await self.get_by_email(user.email) is not None:
            msg = f"User email already exists: {user.email}."
            raise RepositoryIdentityConflictError(msg)
        self._session.add(
            UserRecord(
                id=user.id,
                email=user.email,
                display_name=user.display_name,
                enabled=user.enabled,
                created_at=user.created_at,
                updated_at=user.updated_at,
                version=user.version,
            )
        )
        await self._session.flush()
        return user

    async def get_by_id(self, user_id: UUID) -> User | None:
        """Return one user by technical identifier."""
        record = await self._session.get(UserRecord, user_id)
        return _to_domain(record) if record is not None else None

    async def get_by_email(self, email: str) -> User | None:
        """Return one user by normalized email identity."""
        result = await self._session.execute(
            select(UserRecord).where(UserRecord.email == normalize_email(email))
        )
        record = result.scalar_one_or_none()
        return _to_domain(record) if record is not None else None

    async def set_enabled(
        self,
        user_id: UUID,
        enabled: bool,
        expected_version: int,
    ) -> User | None:
        """Update enabled state when the expected version matches."""
        record = await self._session.get(UserRecord, user_id)
        if record is None or record.version != expected_version:
            return None
        record.enabled = enabled
        record.updated_at = utc_now()
        record.version += 1
        await self._session.flush()
        return _to_domain(record)


def _to_domain(record: UserRecord) -> User:
    return User(
        id=record.id,
        email=record.email,
        display_name=record.display_name,
        enabled=record.enabled,
        created_at=record.created_at,
        updated_at=record.updated_at,
        version=record.version,
    )
