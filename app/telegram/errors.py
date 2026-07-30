from enum import StrEnum


class TelegramFormattingErrorCode(StrEnum):
    """Deterministic formatter validation codes."""

    EMPTY_CONTENT = "empty_content"
    UNSUPPORTED_CHANNEL = "unsupported_channel"
    INVALID_DESTINATION = "invalid_destination"
    MISSING_CORRELATION_ID = "missing_correlation_id"
    INVALID_SOURCE_URL = "invalid_source_url"
    EMPTY_FOOTER = "empty_footer"
    MESSAGE_TOO_LONG = "message_too_long"


_FORMAT_ERROR_MESSAGES = {
    TelegramFormattingErrorCode.EMPTY_CONTENT: "Generated content must not be empty.",
    TelegramFormattingErrorCode.UNSUPPORTED_CHANNEL: (
        "Telegram formatter requires the telegram channel."
    ),
    TelegramFormattingErrorCode.INVALID_DESTINATION: (
        "Telegram destination must be a non-zero numeric chat ID."
    ),
    TelegramFormattingErrorCode.MISSING_CORRELATION_ID: (
        "Delivery correlation ID must not be empty."
    ),
    TelegramFormattingErrorCode.INVALID_SOURCE_URL: (
        "Source URL must be an absolute HTTP or HTTPS URL without credentials."
    ),
    TelegramFormattingErrorCode.EMPTY_FOOTER: (
        "Telegram footer must not be empty when provided."
    ),
    TelegramFormattingErrorCode.MESSAGE_TOO_LONG: (
        "Telegram message exceeds the configured length limit."
    ),
}


class TelegramFormattingError(ValueError):
    """Raised when deterministic Telegram formatting cannot proceed."""

    def __init__(self, code: TelegramFormattingErrorCode) -> None:
        self.code = code
        super().__init__(_FORMAT_ERROR_MESSAGES[code])


class TelegramTransportFailureKind(StrEnum):
    """Transport failures classified without retaining raw exceptions."""

    CONNECT_TIMEOUT = "connect_timeout"
    CONNECT_ERROR = "connect_error"
    POOL_TIMEOUT = "pool_timeout"
    WRITE_TIMEOUT = "write_timeout"
    WRITE_ERROR = "write_error"
    READ_TIMEOUT = "read_timeout"
    READ_ERROR = "read_error"
    REMOTE_PROTOCOL_ERROR = "remote_protocol_error"
    INVALID_REQUEST = "invalid_request"
    OTHER = "other"


_TRANSPORT_ERROR_MESSAGES = {
    TelegramTransportFailureKind.CONNECT_TIMEOUT: (
        "Telegram connection timed out before delivery."
    ),
    TelegramTransportFailureKind.CONNECT_ERROR: (
        "Telegram connection could not be established."
    ),
    TelegramTransportFailureKind.POOL_TIMEOUT: (
        "Telegram connection pool timed out before delivery."
    ),
    TelegramTransportFailureKind.WRITE_TIMEOUT: (
        "Telegram request write timed out; delivery outcome is unknown."
    ),
    TelegramTransportFailureKind.WRITE_ERROR: (
        "Telegram request write failed; delivery outcome is unknown."
    ),
    TelegramTransportFailureKind.READ_TIMEOUT: (
        "Telegram response timed out; delivery outcome is unknown."
    ),
    TelegramTransportFailureKind.READ_ERROR: (
        "Telegram response could not be read; delivery outcome is unknown."
    ),
    TelegramTransportFailureKind.REMOTE_PROTOCOL_ERROR: (
        "Telegram returned an invalid protocol response; delivery is unknown."
    ),
    TelegramTransportFailureKind.INVALID_REQUEST: (
        "Telegram request configuration is invalid."
    ),
    TelegramTransportFailureKind.OTHER: (
        "Telegram transport failed; delivery outcome is unknown."
    ),
}


class TelegramTransportError(RuntimeError):
    """Secret-free transport exception raised by the Bot API client."""

    def __init__(self, kind: TelegramTransportFailureKind) -> None:
        self.kind = kind
        super().__init__(_TRANSPORT_ERROR_MESSAGES[kind])
