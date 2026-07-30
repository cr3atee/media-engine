from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID

from app.delivery.contracts import DeliveryMessage
from app.telegram.errors import (
    TelegramFormattingError,
    TelegramFormattingErrorCode,
)
from app.telegram.security import is_valid_telegram_destination

TELEGRAM_MESSAGE_LIMIT = 4096


@dataclass(slots=True, frozen=True, kw_only=True)
class TelegramFormattingRequest:
    """Application data required to render one plain-text Telegram message."""

    publication_id: UUID
    channel: str
    destination_id: str
    generated_text: str
    correlation_id: str
    source_url: str | None = None
    footer: str | None = None
    reference_id: str | None = None
    disable_web_page_preview: bool = True


class TelegramPlainTextFormatter:
    """Build deterministic Telegram plain text without markup or splitting."""

    def __init__(self, *, maximum_length: int = TELEGRAM_MESSAGE_LIMIT) -> None:
        if maximum_length < 1 or maximum_length > TELEGRAM_MESSAGE_LIMIT:
            msg = "Telegram maximum length must be between 1 and 4096."
            raise ValueError(msg)
        self._maximum_length = maximum_length

    def format(self, request: TelegramFormattingRequest) -> DeliveryMessage:
        """Validate and render one immutable Telegram delivery message."""
        channel = request.channel.strip().lower()
        if channel != "telegram":
            raise TelegramFormattingError(
                TelegramFormattingErrorCode.UNSUPPORTED_CHANNEL
            )

        destination_id = request.destination_id.strip()
        if not is_valid_telegram_destination(destination_id):
            raise TelegramFormattingError(
                TelegramFormattingErrorCode.INVALID_DESTINATION
            )

        correlation_id = request.correlation_id.strip()
        if not correlation_id:
            raise TelegramFormattingError(
                TelegramFormattingErrorCode.MISSING_CORRELATION_ID
            )

        content = _normalize_plain_text(request.generated_text)
        if not content:
            raise TelegramFormattingError(TelegramFormattingErrorCode.EMPTY_CONTENT)

        parts = [content]
        if request.source_url is not None:
            parts.append(_validate_source_url(request.source_url))
        if request.footer is not None:
            footer = _normalize_plain_text(request.footer)
            if not footer:
                raise TelegramFormattingError(TelegramFormattingErrorCode.EMPTY_FOOTER)
            parts.append(footer)

        rendered_text = "\n\n".join(parts)
        if len(rendered_text) > self._maximum_length:
            raise TelegramFormattingError(TelegramFormattingErrorCode.MESSAGE_TOO_LONG)

        return DeliveryMessage(
            publication_id=request.publication_id,
            channel=channel,
            destination_id=destination_id,
            rendered_text=rendered_text,
            correlation_id=correlation_id,
            disable_web_page_preview=request.disable_web_page_preview,
            parse_mode=None,
            reference_id=request.reference_id,
        )


def _normalize_plain_text(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.expandtabs(4)
    normalized = "".join(
        character
        for character in normalized
        if character == "\n" or unicodedata.category(character) != "Cc"
    )
    lines = [line.rstrip() for line in normalized.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def _validate_source_url(value: str) -> str:
    if value != value.strip() or any(
        character.isspace() or unicodedata.category(character) == "Cc"
        for character in value
    ):
        raise TelegramFormattingError(TelegramFormattingErrorCode.INVALID_SOURCE_URL)
    parsed = urlsplit(value)
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise TelegramFormattingError(TelegramFormattingErrorCode.INVALID_SOURCE_URL)
    return value
