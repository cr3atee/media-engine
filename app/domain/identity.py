from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256


def normalize_utc(value: datetime, *, field_name: str) -> datetime:
    """Return an aware datetime normalized to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        msg = f"{field_name} must be timezone-aware."
        raise ValueError(msg)
    return value.astimezone(UTC)


def canonicalize_utc(value: datetime) -> str:
    """Serialize an aware datetime as a stable UTC value."""
    normalized = normalize_utc(value, field_name="timestamp")
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonicalize_decimal(value: Decimal) -> str:
    """Serialize a finite Decimal without exponent or insignificant zeros."""
    if not isinstance(value, Decimal):
        msg = "Identity monetary values must use Decimal."
        raise TypeError(msg)
    if not value.is_finite():
        msg = "Identity monetary values must be finite."
        raise ValueError(msg)

    serialized = format(value, "f")
    if "." in serialized:
        serialized = serialized.rstrip("0").rstrip(".")
    return "0" if serialized in {"", "-0"} else serialized


def canonicalize_identity_fields(*fields: str) -> str:
    """Join identity fields with deterministic escaping."""
    return "|".join(_escape_identity_field(field) for field in fields)


def hash_identity_fields(*fields: str) -> str:
    """Return a lowercase SHA-256 digest for canonical identity fields."""
    canonical = canonicalize_identity_fields(*fields)
    return sha256(canonical.encode("utf-8")).hexdigest()


def validate_sha256(value: str, *, field_name: str) -> None:
    """Validate a lowercase hexadecimal SHA-256 value."""
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        msg = f"{field_name} must be a lowercase hexadecimal SHA-256 value."
        raise ValueError(msg)


def _escape_identity_field(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|")
