from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from app.domain.auth import AuthSession, PasswordCredential, PasswordResetToken
from app.domain.tenancy import utc_now
from app.repositories.auth import (
    AuthSessionRepository,
    PasswordCredentialRepository,
    PasswordResetTokenRepository,
)
from app.repositories.base import RepositoryIdentityConflictError


class MemoryPasswordCredentialRepository(PasswordCredentialRepository):
    """Deterministic in-memory repository for password verifiers."""

    def __init__(self) -> None:
        """Initialize isolated credential storage."""
        self._credentials_by_user_id: dict[UUID, PasswordCredential] = {}

    async def set_for_user(self, credential: PasswordCredential) -> PasswordCredential:
        """Create or replace one user's password verifier."""
        existing = self._credentials_by_user_id.get(credential.user_id)
        stored = (
            credential
            if existing is None
            else replace(
                credential,
                created_at=existing.created_at,
                version=existing.version + 1,
            )
        )
        self._credentials_by_user_id[credential.user_id] = stored
        return stored

    async def get_by_user_id(self, user_id: UUID) -> PasswordCredential | None:
        """Return one user's password verifier."""
        return self._credentials_by_user_id.get(user_id)


class MemoryAuthSessionRepository(AuthSessionRepository):
    """Deterministic in-memory repository for refresh-token sessions."""

    def __init__(self) -> None:
        """Initialize isolated session storage."""
        self._sessions_by_id: dict[UUID, AuthSession] = {}
        self._session_ids_by_refresh_hash: dict[str, UUID] = {}

    async def create(self, session: AuthSession) -> AuthSession:
        """Persist one session while enforcing refresh-token uniqueness."""
        if session.id in self._sessions_by_id:
            msg = f"Auth session ID already exists: {session.id}."
            raise RepositoryIdentityConflictError(msg)
        if session.refresh_token_hash in self._session_ids_by_refresh_hash:
            msg = "Refresh token hash already exists."
            raise RepositoryIdentityConflictError(msg)
        self._sessions_by_id[session.id] = session
        self._session_ids_by_refresh_hash[session.refresh_token_hash] = session.id
        return session

    async def get_by_id(self, session_id: UUID) -> AuthSession | None:
        """Return one session by technical identifier."""
        return self._sessions_by_id.get(session_id)

    async def get_by_refresh_token_hash(
        self,
        refresh_token_hash: str,
    ) -> AuthSession | None:
        """Return one session by refresh-token hash."""
        session_id = self._session_ids_by_refresh_hash.get(refresh_token_hash)
        return self._sessions_by_id.get(session_id) if session_id is not None else None

    async def rotate_refresh_token(
        self,
        session_id: UUID,
        current_refresh_token_hash: str,
        new_refresh_token_hash: str,
        expected_version: int,
    ) -> AuthSession | None:
        """Replace the refresh-token hash when the expected version matches."""
        session = self._sessions_by_id.get(session_id)
        if (
            session is None
            or session.version != expected_version
            or session.refresh_token_hash != current_refresh_token_hash
        ):
            return None
        if new_refresh_token_hash in self._session_ids_by_refresh_hash:
            msg = "Refresh token hash already exists."
            raise RepositoryIdentityConflictError(msg)
        updated = replace(
            session,
            refresh_token_hash=new_refresh_token_hash,
            last_used_at=utc_now(),
            version=session.version + 1,
        )
        del self._session_ids_by_refresh_hash[current_refresh_token_hash]
        self._sessions_by_id[session_id] = updated
        self._session_ids_by_refresh_hash[new_refresh_token_hash] = session_id
        return updated

    async def revoke(
        self, session_id: UUID, expected_version: int
    ) -> AuthSession | None:
        """Revoke one session when the expected version matches."""
        session = self._sessions_by_id.get(session_id)
        if session is None or session.version != expected_version:
            return None
        updated = replace(
            session,
            revoked_at=utc_now(),
            version=session.version + 1,
        )
        self._sessions_by_id[session_id] = updated
        return updated

    async def revoke_all_for_user(self, user_id: UUID) -> int:
        """Revoke every active session for one user."""
        now = utc_now()
        count = 0
        for session_id, session in tuple(self._sessions_by_id.items()):
            if session.user_id == user_id and session.revoked_at is None:
                self._sessions_by_id[session_id] = replace(
                    session,
                    revoked_at=now,
                    version=session.version + 1,
                )
                count += 1
        return count


class MemoryPasswordResetTokenRepository(PasswordResetTokenRepository):
    """Deterministic in-memory repository for reset token hashes."""

    def __init__(self) -> None:
        """Initialize isolated reset token storage."""
        self._tokens_by_id: dict[UUID, PasswordResetToken] = {}
        self._token_ids_by_hash: dict[str, UUID] = {}

    async def create(self, token: PasswordResetToken) -> PasswordResetToken:
        """Persist one reset token while enforcing hash uniqueness."""
        if token.id in self._tokens_by_id:
            msg = f"Password reset token ID already exists: {token.id}."
            raise RepositoryIdentityConflictError(msg)
        if token.token_hash in self._token_ids_by_hash:
            msg = "Password reset token hash already exists."
            raise RepositoryIdentityConflictError(msg)
        self._tokens_by_id[token.id] = token
        self._token_ids_by_hash[token.token_hash] = token.id
        return token

    async def get_by_token_hash(self, token_hash: str) -> PasswordResetToken | None:
        """Return one reset token by hash."""
        token_id = self._token_ids_by_hash.get(token_hash)
        return self._tokens_by_id.get(token_id) if token_id is not None else None

    async def mark_used(
        self,
        token_id: UUID,
        expected_version: int,
    ) -> PasswordResetToken | None:
        """Mark one reset token as consumed when the expected version matches."""
        token = self._tokens_by_id.get(token_id)
        if token is None or token.version != expected_version or token.used_at:
            return None
        updated = replace(token, used_at=utc_now(), version=token.version + 1)
        self._tokens_by_id[token_id] = updated
        return updated
