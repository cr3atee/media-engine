from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from app.domain.auth import (
    ActorType,
    AuthenticatedPrincipal,
    AuthSession,
    PasswordCredential,
    PasswordResetToken,
)
from app.domain.tenancy import normalize_email, utc_now
from app.services.auth_tokens import (
    SignedAccessTokenService,
    generate_opaque_token,
    hash_opaque_token,
)
from app.services.passwords import PasswordHasher
from app.services.repository_scope import RepositoryScopeFactory

type Clock = Callable[[], datetime]
type TokenFactory = Callable[[], str]
type UuidFactory = Callable[[], UUID]


class AuthenticationError(Exception):
    """Safe authentication failure with stable public status."""

    def __init__(self, code: str, message: str, *, status_code: int = 401) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass(slots=True, frozen=True, kw_only=True)
class TokenPair:
    """Access and refresh tokens returned after login or refresh."""

    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


@dataclass(slots=True, frozen=True, kw_only=True)
class PasswordResetRequestResult:
    """Internal result of a reset request; APIs must not expose the token."""

    accepted: bool
    reset_token: str | None


class AuthenticationService:
    """Authenticate users and manage durable refresh-token sessions."""

    def __init__(
        self,
        repository_scope_factory: RepositoryScopeFactory,
        token_service: SignedAccessTokenService,
        password_hasher: PasswordHasher,
        *,
        access_token_ttl_seconds: int,
        refresh_token_ttl_seconds: int,
        password_reset_token_ttl_seconds: int,
        clock: Clock = utc_now,
        session_id_factory: UuidFactory = uuid4,
        reset_token_id_factory: UuidFactory = uuid4,
        opaque_token_factory: TokenFactory = generate_opaque_token,
    ) -> None:
        """Bind authentication to repositories and deterministic collaborators."""
        self._repository_scope_factory = repository_scope_factory
        self._token_service = token_service
        self._password_hasher = password_hasher
        self._access_token_ttl_seconds = access_token_ttl_seconds
        self._refresh_token_ttl_seconds = refresh_token_ttl_seconds
        self._password_reset_token_ttl_seconds = password_reset_token_ttl_seconds
        self._clock = clock
        self._session_id_factory = session_id_factory
        self._reset_token_id_factory = reset_token_id_factory
        self._opaque_token_factory = opaque_token_factory

    async def login(self, *, email: str, password: str) -> TokenPair:
        """Authenticate a user and create a durable refresh session."""
        try:
            normalized_email = normalize_email(email)
        except ValueError as exc:
            raise _invalid_credentials() from exc
        now = self._clock()
        async with self._repository_scope_factory() as repositories:
            user = await repositories.users.get_by_email(normalized_email)
            if user is None:
                raise _invalid_credentials()
            if not user.enabled:
                raise AuthenticationError(
                    "account_disabled",
                    "User account is disabled.",
                    status_code=403,
                )
            credential = await repositories.password_credentials.get_by_user_id(user.id)
            if credential is None or not self._password_hasher.verify(
                password,
                credential.password_hash,
            ):
                raise _invalid_credentials()
            refresh_token = self._opaque_token_factory()
            session = AuthSession(
                id=self._session_id_factory(),
                user_id=user.id,
                refresh_token_hash=hash_opaque_token(refresh_token),
                created_at=now,
                expires_at=now + timedelta(seconds=self._refresh_token_ttl_seconds),
            )
            await repositories.auth_sessions.create(session)
        return self._tokens_for(
            user_id=user.id,
            session_id=session.id,
            refresh_token=refresh_token,
            issued_at=now,
        )

    async def refresh(self, *, refresh_token: str) -> TokenPair:
        """Rotate a refresh token and issue a fresh access token."""
        now = self._clock()
        current_hash = hash_opaque_token(refresh_token)
        async with self._repository_scope_factory() as repositories:
            session = await repositories.auth_sessions.get_by_refresh_token_hash(
                current_hash
            )
            if session is None or not session.is_active(now):
                raise _invalid_refresh()
            user = await repositories.users.get_by_id(session.user_id)
            if user is None or not user.enabled:
                raise _invalid_refresh()
            new_refresh_token = self._opaque_token_factory()
            rotated = await repositories.auth_sessions.rotate_refresh_token(
                session.id,
                current_hash,
                hash_opaque_token(new_refresh_token),
                session.version,
            )
            if rotated is None:
                raise _invalid_refresh()
        return self._tokens_for(
            user_id=rotated.user_id,
            session_id=rotated.id,
            refresh_token=new_refresh_token,
            issued_at=now,
        )

    async def logout(self, *, refresh_token: str) -> None:
        """Revoke a refresh session; invalid tokens do not reveal state."""
        current_hash = hash_opaque_token(refresh_token)
        async with self._repository_scope_factory() as repositories:
            session = await repositories.auth_sessions.get_by_refresh_token_hash(
                current_hash
            )
            if session is not None and session.revoked_at is None:
                await repositories.auth_sessions.revoke(session.id, session.version)

    async def authenticate_access_token(
        self,
        access_token: str,
    ) -> AuthenticatedPrincipal:
        """Resolve one bearer token to a current active principal."""
        now = self._clock()
        claims = self._token_service.parse_access_token(access_token, now=now)
        async with self._repository_scope_factory() as repositories:
            session = await repositories.auth_sessions.get_by_id(claims.session_id)
            if (
                session is None
                or session.user_id != claims.user_id
                or not session.is_active(now)
            ):
                raise AuthenticationError(
                    "token_revoked",
                    "Access token session is no longer active.",
                )
            user = await repositories.users.get_by_id(claims.user_id)
            if user is None or not user.enabled:
                raise AuthenticationError(
                    "account_disabled",
                    "User account is disabled.",
                    status_code=403,
                )
        return AuthenticatedPrincipal(
            actor_type=ActorType.USER,
            user_id=claims.user_id,
            session_id=claims.session_id,
            issued_at=claims.issued_at,
            expires_at=claims.expires_at,
        )

    async def request_password_reset(self, *, email: str) -> PasswordResetRequestResult:
        """Create a reset token when the user exists while returning safe status."""
        try:
            normalized_email = normalize_email(email)
        except ValueError:
            return PasswordResetRequestResult(accepted=True, reset_token=None)
        now = self._clock()
        async with self._repository_scope_factory() as repositories:
            user = await repositories.users.get_by_email(normalized_email)
            if user is None or not user.enabled:
                return PasswordResetRequestResult(accepted=True, reset_token=None)
            reset_token = self._opaque_token_factory()
            await repositories.password_reset_tokens.create(
                PasswordResetToken(
                    id=self._reset_token_id_factory(),
                    user_id=user.id,
                    token_hash=hash_opaque_token(reset_token),
                    created_at=now,
                    expires_at=now
                    + timedelta(seconds=self._password_reset_token_ttl_seconds),
                )
            )
        return PasswordResetRequestResult(accepted=True, reset_token=reset_token)

    async def complete_password_reset(
        self,
        *,
        reset_token: str,
        new_password: str,
    ) -> None:
        """Consume a reset token, update credentials, and revoke sessions."""
        now = self._clock()
        token_hash = hash_opaque_token(reset_token)
        async with self._repository_scope_factory() as repositories:
            token = await repositories.password_reset_tokens.get_by_token_hash(
                token_hash
            )
            if token is None or not token.is_usable(now):
                raise AuthenticationError(
                    "reset_token_invalid",
                    "Password reset token is invalid or expired.",
                    status_code=400,
                )
            await repositories.password_credentials.set_for_user(
                PasswordCredential(
                    user_id=token.user_id,
                    password_hash=self._password_hasher.hash_password(new_password),
                    created_at=now,
                    updated_at=now,
                )
            )
            used = await repositories.password_reset_tokens.mark_used(
                token.id,
                token.version,
            )
            if used is None:
                raise AuthenticationError(
                    "reset_token_invalid",
                    "Password reset token is invalid or expired.",
                    status_code=400,
                )
            await repositories.auth_sessions.revoke_all_for_user(token.user_id)

    def _tokens_for(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
        refresh_token: str,
        issued_at: datetime,
    ) -> TokenPair:
        return TokenPair(
            access_token=self._token_service.create_access_token(
                user_id=user_id,
                session_id=session_id,
                issued_at=issued_at,
            ),
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=self._access_token_ttl_seconds,
        )


def _invalid_credentials() -> AuthenticationError:
    return AuthenticationError(
        "invalid_credentials",
        "Email or password is invalid.",
    )


def _invalid_refresh() -> AuthenticationError:
    return AuthenticationError(
        "token_revoked",
        "Refresh token is invalid or revoked.",
    )
