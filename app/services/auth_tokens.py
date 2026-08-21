from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID


class AuthTokenError(Exception):
    """Safe token parsing failure with a stable error code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(slots=True, frozen=True, kw_only=True)
class AccessTokenClaims:
    """Verified signed access-token claims."""

    user_id: UUID
    session_id: UUID
    issued_at: datetime
    expires_at: datetime


class SignedAccessTokenService:
    """Issue and verify short-lived HMAC-signed access tokens."""

    _version = "ME1"

    def __init__(
        self,
        *,
        secret: str,
        ttl_seconds: int,
        issuer: str,
        audience: str,
        clock: object | None = None,
    ) -> None:
        """Configure signing and validation metadata."""
        if not secret.strip():
            msg = "Auth access token secret is not configured."
            raise ValueError(msg)
        if ttl_seconds <= 0:
            msg = "Access token TTL must be positive."
            raise ValueError(msg)
        self._secret = secret.encode("utf-8")
        self._ttl_seconds = ttl_seconds
        self._issuer = issuer
        self._audience = audience

    def create_access_token(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
        issued_at: datetime,
    ) -> str:
        """Create one signed access token for a durable session."""
        issued = _epoch(issued_at)
        expires = _epoch(issued_at + timedelta(seconds=self._ttl_seconds))
        payload = {
            "aud": self._audience,
            "exp": expires,
            "iat": issued,
            "iss": self._issuer,
            "sid": str(session_id),
            "sub": str(user_id),
        }
        encoded_payload = _encode_json(payload)
        signature = _signature(self._secret, encoded_payload)
        return f"{self._version}.{encoded_payload}.{signature}"

    def parse_access_token(self, token: str, *, now: datetime) -> AccessTokenClaims:
        """Verify and parse one access token."""
        try:
            version, encoded_payload, supplied_signature = token.split(".", 2)
        except ValueError as exc:
            raise AuthTokenError("invalid_token", "Access token is invalid.") from exc
        if version != self._version:
            raise AuthTokenError("invalid_token", "Access token is invalid.")
        expected_signature = _signature(self._secret, encoded_payload)
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise AuthTokenError("invalid_token", "Access token is invalid.")
        payload = _decode_json(encoded_payload)
        if payload.get("iss") != self._issuer or payload.get("aud") != self._audience:
            raise AuthTokenError("invalid_token", "Access token is invalid.")
        expires_at = _from_epoch(payload.get("exp"))
        if expires_at <= now.astimezone(UTC):
            raise AuthTokenError("token_expired", "Access token has expired.")
        issued_at = _from_epoch(payload.get("iat"))
        try:
            user_id = UUID(str(payload["sub"]))
            session_id = UUID(str(payload["sid"]))
        except (KeyError, ValueError) as exc:
            raise AuthTokenError("invalid_token", "Access token is invalid.") from exc
        return AccessTokenClaims(
            user_id=user_id,
            session_id=session_id,
            issued_at=issued_at,
            expires_at=expires_at,
        )


def generate_opaque_token() -> str:
    """Create a high-entropy opaque token for refresh/reset flows."""
    return secrets.token_urlsafe(48)


def hash_opaque_token(token: str) -> str:
    """Hash an opaque token for durable storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _signature(secret: bytes, encoded_payload: str) -> str:
    digest = hmac.new(secret, encoded_payload.encode("ascii"), hashlib.sha256).digest()
    return _encode_bytes(digest)


def _encode_json(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return _encode_bytes(raw)


def _decode_json(value: str) -> dict[str, Any]:
    try:
        raw = _decode_bytes(value)
        decoded = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise AuthTokenError("invalid_token", "Access token is invalid.") from exc
    if not isinstance(decoded, dict):
        raise AuthTokenError("invalid_token", "Access token is invalid.")
    return decoded


def _encode_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_bytes(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


def _epoch(value: datetime) -> int:
    return int(value.astimezone(UTC).timestamp())


def _from_epoch(value: object) -> datetime:
    if not isinstance(value, int):
        raise AuthTokenError("invalid_token", "Access token is invalid.")
    return datetime.fromtimestamp(value, UTC)
