from __future__ import annotations

from abc import abstractmethod
from uuid import UUID

from app.domain.auth import AuthSession, PasswordCredential, PasswordResetToken
from app.repositories.base import BaseRepository


class PasswordCredentialRepository(BaseRepository):
    """Abstract storage contract for user password verifiers."""

    @abstractmethod
    async def set_for_user(self, credential: PasswordCredential) -> PasswordCredential:
        """Create or replace one user's password verifier."""

    @abstractmethod
    async def get_by_user_id(self, user_id: UUID) -> PasswordCredential | None:
        """Return one user's password verifier when configured."""


class AuthSessionRepository(BaseRepository):
    """Abstract storage contract for durable refresh-token sessions."""

    @abstractmethod
    async def create(self, session: AuthSession) -> AuthSession:
        """Persist a new refresh-token session."""

    @abstractmethod
    async def get_by_id(self, session_id: UUID) -> AuthSession | None:
        """Return one session by technical identifier."""

    @abstractmethod
    async def get_by_refresh_token_hash(
        self,
        refresh_token_hash: str,
    ) -> AuthSession | None:
        """Return one session by stored refresh-token hash."""

    @abstractmethod
    async def rotate_refresh_token(
        self,
        session_id: UUID,
        current_refresh_token_hash: str,
        new_refresh_token_hash: str,
        expected_version: int,
    ) -> AuthSession | None:
        """Replace the refresh-token hash using optimistic version guarding."""

    @abstractmethod
    async def revoke(
        self, session_id: UUID, expected_version: int
    ) -> AuthSession | None:
        """Revoke one session using optimistic version guarding."""

    @abstractmethod
    async def revoke_all_for_user(self, user_id: UUID) -> int:
        """Revoke every active session for one user and return affected count."""


class PasswordResetTokenRepository(BaseRepository):
    """Abstract storage contract for one-use password reset token hashes."""

    @abstractmethod
    async def create(self, token: PasswordResetToken) -> PasswordResetToken:
        """Persist a new password reset token hash."""

    @abstractmethod
    async def get_by_token_hash(self, token_hash: str) -> PasswordResetToken | None:
        """Return one reset token by stored hash."""

    @abstractmethod
    async def mark_used(
        self,
        token_id: UUID,
        expected_version: int,
    ) -> PasswordResetToken | None:
        """Mark a reset token as consumed using optimistic version guarding."""
