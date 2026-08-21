from __future__ import annotations

import base64
import hashlib
import secrets


class PasswordHasher:
    """Hash and verify passwords using only the standard library.

    The implementation is intentionally isolated behind this service so it can
    be replaced by Argon2id without changing authentication workflows.
    """

    algorithm = "pbkdf2_sha256"

    def __init__(self, *, iterations: int) -> None:
        """Configure the PBKDF2 work factor."""
        if iterations < 100_000:
            msg = "Password hash iterations must be at least 100000."
            raise ValueError(msg)
        self._iterations = iterations

    def hash_password(self, password: str) -> str:
        """Return a salted password verifier string."""
        _require_password(password)
        salt = secrets.token_bytes(16)
        digest = _derive(password, salt, self._iterations)
        return "$".join(
            (
                self.algorithm,
                str(self._iterations),
                _encode(salt),
                _encode(digest),
            )
        )

    def verify(self, password: str, password_hash: str) -> bool:
        """Verify a password using constant-time digest comparison."""
        try:
            algorithm, iterations, salt, expected = password_hash.split("$", 3)
            if algorithm != self.algorithm:
                return False
            parsed_iterations = int(iterations)
            salt_bytes = _decode(salt)
            expected_bytes = _decode(expected)
        except (ValueError, TypeError):
            return False
        actual = _derive(password, salt_bytes, parsed_iterations)
        return secrets.compare_digest(actual, expected_bytes)


def _require_password(value: str) -> None:
    if len(value) < 12:
        msg = "Password must be at least 12 characters long."
        raise ValueError(msg)


def _derive(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))
