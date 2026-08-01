from __future__ import annotations

import hashlib
import re

_BOT_TOKEN_PATTERN = re.compile(r"(?<![A-Za-z0-9_])[0-9]{5,}:[A-Za-z0-9_-]{8,}")
_CONTROL_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
_MAX_ERROR_LENGTH = 240


def safe_error(
    code: str | None,
    summary: str | None,
) -> tuple[str | None, str | None]:
    """Return bounded error fields without credential-shaped text."""
    if code is None and summary is None:
        return None, None

    safe_code = _sanitize(code or "")[:128] or "internal_error"
    safe_summary = _sanitize(summary or "")[:_MAX_ERROR_LENGTH]
    return safe_code, safe_summary or None


def destination_reference(destination: str) -> str:
    """Return a stable non-reversible reference for a publication destination."""
    return hashlib.sha256(destination.encode("utf-8")).hexdigest()[:12]


def safe_label(value: str | None, *, maximum: int = 128) -> str | None:
    """Return a bounded non-secret provider/model label."""
    if value is None:
        return None
    cleaned = _sanitize(value)[:maximum]
    return cleaned or None


def _sanitize(value: str) -> str:
    value = _CONTROL_PATTERN.sub(" ", value).strip()
    return _BOT_TOKEN_PATTERN.sub("[REDACTED]", value)
