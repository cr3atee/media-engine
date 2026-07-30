from __future__ import annotations

import hashlib
import re
from urllib.parse import quote

_NUMERIC_DESTINATION = re.compile(r"-?[1-9][0-9]*\Z")
_BOT_TOKEN = re.compile(r"(?<![A-Za-z0-9_])[0-9]{5,}:[A-Za-z0-9_-]{8,}")
_MAX_SAFE_MESSAGE_LENGTH = 240


def is_valid_telegram_destination(value: str) -> bool:
    """Return whether value is a supported numeric Telegram chat ID."""
    return bool(_NUMERIC_DESTINATION.fullmatch(value))


def redact_sensitive_text(value: str, *, token: str = "") -> str:
    """Remove a known or token-shaped Bot API credential from text."""
    redacted = value
    if token:
        variants = {token, quote(token, safe=""), quote(token, safe=":")}
        for variant in variants:
            if variant:
                redacted = redacted.replace(variant, "[REDACTED]")
    return _BOT_TOKEN.sub("[REDACTED]", redacted)


def sanitize_provider_message(value: str | None, *, token: str) -> str | None:
    """Return one bounded credential-free provider description."""
    if value is None:
        return None
    sanitized = redact_sensitive_text(value, token=token).strip()
    if not sanitized:
        return None
    return sanitized[:_MAX_SAFE_MESSAGE_LENGTH]


def safe_destination_reference(destination_id: str) -> str:
    """Return a stable non-reversible destination reference for logs."""
    return hashlib.sha256(destination_id.encode("utf-8")).hexdigest()[:12]
