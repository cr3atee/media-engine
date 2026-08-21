from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.auth import AuthSession, PasswordCredential, PasswordResetToken
from app.domain.tenancy import utc_now
from app.models.auth_record import (
    AuthSessionRecord,
    PasswordResetTokenRecord,
    UserCredentialRecord,
)
from app.repositories.auth import (
    AuthSessionRepository,
    PasswordCredentialRepository,
    PasswordResetTokenRepository,
)
from app.repositories.base import RepositoryIdentityConflictError


class PostgresPasswordCredentialRepository(PasswordCredentialRepository):
    """PostgreSQL-backed repository for password verifier hashes."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a caller-owned session and transaction."""
        self._session = session

    async def set_for_user(self, credential: PasswordCredential) -> PasswordCredential:
        """Create or replace one user's password verifier."""
        record = await self._session.get(UserCredentialRecord, credential.user_id)
        if record is None:
            self._session.add(
                UserCredentialRecord(
                    user_id=credential.user_id,
                    password_hash=credential.password_hash,
                    created_at=credential.created_at,
                    updated_at=credential.updated_at,
                    version=credential.version,
                )
            )
            await self._session.flush()
            return credential

        record.password_hash = credential.password_hash
        record.updated_at = credential.updated_at
        record.version += 1
        await self._session.flush()
        return _credential_to_domain(record)

    async def get_by_user_id(self, user_id: UUID) -> PasswordCredential | None:
        """Return one user's password verifier."""
        record = await self._session.get(UserCredentialRecord, user_id)
        return _credential_to_domain(record) if record is not None else None


class PostgresAuthSessionRepository(AuthSessionRepository):
    """PostgreSQL-backed repository for refresh-token sessions."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a caller-owned session and transaction."""
        self._session = session

    async def create(self, session: AuthSession) -> AuthSession:
        """Persist one session while enforcing refresh-token uniqueness."""
        if await self.get_by_id(session.id) is not None:
            msg = f"Auth session ID already exists: {session.id}."
            raise RepositoryIdentityConflictError(msg)
        if await self.get_by_refresh_token_hash(session.refresh_token_hash) is not None:
            msg = "Refresh token hash already exists."
            raise RepositoryIdentityConflictError(msg)
        self._session.add(
            AuthSessionRecord(
                id=session.id,
                user_id=session.user_id,
                refresh_token_hash=session.refresh_token_hash,
                created_at=session.created_at,
                expires_at=session.expires_at,
                revoked_at=session.revoked_at,
                last_used_at=session.last_used_at,
                version=session.version,
            )
        )
        await self._session.flush()
        return session

    async def get_by_id(self, session_id: UUID) -> AuthSession | None:
        """Return one session by technical identifier."""
        record = await self._session.get(AuthSessionRecord, session_id)
        return _session_to_domain(record) if record is not None else None

    async def get_by_refresh_token_hash(
        self,
        refresh_token_hash: str,
    ) -> AuthSession | None:
        """Return one session by refresh-token hash."""
        result = await self._session.execute(
            select(AuthSessionRecord).where(
                AuthSessionRecord.refresh_token_hash == refresh_token_hash
            )
        )
        record = result.scalar_one_or_none()
        return _session_to_domain(record) if record is not None else None

    async def rotate_refresh_token(
        self,
        session_id: UUID,
        current_refresh_token_hash: str,
        new_refresh_token_hash: str,
        expected_version: int,
    ) -> AuthSession | None:
        """Replace the refresh-token hash when the expected version matches."""
        if await self.get_by_refresh_token_hash(new_refresh_token_hash) is not None:
            msg = "Refresh token hash already exists."
            raise RepositoryIdentityConflictError(msg)
        record = await self._session.get(AuthSessionRecord, session_id)
        if (
            record is None
            or record.version != expected_version
            or record.refresh_token_hash != current_refresh_token_hash
        ):
            return None
        record.refresh_token_hash = new_refresh_token_hash
        record.last_used_at = utc_now()
        record.version += 1
        await self._session.flush()
        return _session_to_domain(record)

    async def revoke(
        self, session_id: UUID, expected_version: int
    ) -> AuthSession | None:
        """Revoke one session when the expected version matches."""
        record = await self._session.get(AuthSessionRecord, session_id)
        if record is None or record.version != expected_version:
            return None
        record.revoked_at = utc_now()
        record.version += 1
        await self._session.flush()
        return _session_to_domain(record)

    async def revoke_all_for_user(self, user_id: UUID) -> int:
        """Revoke every active session for one user."""
        now = utc_now()
        result = await self._session.execute(
            select(AuthSessionRecord).where(
                AuthSessionRecord.user_id == user_id,
                AuthSessionRecord.revoked_at.is_(None),
            )
        )
        records = tuple(result.scalars())
        for record in records:
            record.revoked_at = now
            record.version += 1
        await self._session.flush()
        return len(records)


class PostgresPasswordResetTokenRepository(PasswordResetTokenRepository):
    """PostgreSQL-backed repository for reset token hashes."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a caller-owned session and transaction."""
        self._session = session

    async def create(self, token: PasswordResetToken) -> PasswordResetToken:
        """Persist one reset token while enforcing hash uniqueness."""
        if await self._session.get(PasswordResetTokenRecord, token.id) is not None:
            msg = f"Password reset token ID already exists: {token.id}."
            raise RepositoryIdentityConflictError(msg)
        if await self.get_by_token_hash(token.token_hash) is not None:
            msg = "Password reset token hash already exists."
            raise RepositoryIdentityConflictError(msg)
        self._session.add(
            PasswordResetTokenRecord(
                id=token.id,
                user_id=token.user_id,
                token_hash=token.token_hash,
                created_at=token.created_at,
                expires_at=token.expires_at,
                used_at=token.used_at,
                version=token.version,
            )
        )
        await self._session.flush()
        return token

    async def get_by_token_hash(self, token_hash: str) -> PasswordResetToken | None:
        """Return one reset token by hash."""
        result = await self._session.execute(
            select(PasswordResetTokenRecord).where(
                PasswordResetTokenRecord.token_hash == token_hash
            )
        )
        record = result.scalar_one_or_none()
        return _reset_token_to_domain(record) if record is not None else None

    async def mark_used(
        self,
        token_id: UUID,
        expected_version: int,
    ) -> PasswordResetToken | None:
        """Mark one reset token as consumed when the expected version matches."""
        record = await self._session.get(PasswordResetTokenRecord, token_id)
        if record is None or record.version != expected_version or record.used_at:
            return None
        record.used_at = utc_now()
        record.version += 1
        await self._session.flush()
        return _reset_token_to_domain(record)


def _credential_to_domain(record: UserCredentialRecord) -> PasswordCredential:
    return PasswordCredential(
        user_id=record.user_id,
        password_hash=record.password_hash,
        created_at=record.created_at,
        updated_at=record.updated_at,
        version=record.version,
    )


def _session_to_domain(record: AuthSessionRecord) -> AuthSession:
    return AuthSession(
        id=record.id,
        user_id=record.user_id,
        refresh_token_hash=record.refresh_token_hash,
        created_at=record.created_at,
        expires_at=record.expires_at,
        revoked_at=record.revoked_at,
        last_used_at=record.last_used_at,
        version=record.version,
    )


def _reset_token_to_domain(record: PasswordResetTokenRecord) -> PasswordResetToken:
    return PasswordResetToken(
        id=record.id,
        user_id=record.user_id,
        token_hash=record.token_hash,
        created_at=record.created_at,
        expires_at=record.expires_at,
        used_at=record.used_at,
        version=record.version,
    )
