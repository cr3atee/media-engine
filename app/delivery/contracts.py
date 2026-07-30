from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID


class DeliveryOutcome(StrEnum):
    """Channel-independent outcome of one adapter call."""

    SUCCESS = "success"
    RETRYABLE_FAILURE = "retryable_failure"
    PERMANENT_FAILURE = "permanent_failure"
    AMBIGUOUS = "ambiguous"
    INVALID_REQUEST = "invalid_request"


class DeliveryErrorCategory(StrEnum):
    """Safe categories exposed by delivery adapters."""

    UNSUPPORTED_CHANNEL = "unsupported_channel"
    INVALID_DESTINATION = "invalid_destination"
    INVALID_CONTENT = "invalid_content"
    MESSAGE_TOO_LONG = "message_too_long"
    INVALID_CLIENT_STATE = "invalid_client_state"
    CONNECT_TIMEOUT = "connect_timeout"
    CONNECT_ERROR = "connect_error"
    POOL_TIMEOUT = "pool_timeout"
    WRITE_TIMEOUT = "write_timeout"
    WRITE_ERROR = "write_error"
    READ_TIMEOUT = "read_timeout"
    READ_ERROR = "read_error"
    REMOTE_PROTOCOL_ERROR = "remote_protocol_error"
    MALFORMED_RESPONSE = "malformed_response"
    DESTINATION_MISMATCH = "destination_mismatch"
    RATE_LIMITED = "rate_limited"
    PROVIDER_CLIENT_ERROR = "provider_client_error"
    PROVIDER_SERVER_ERROR = "provider_server_error"
    PROVIDER_REJECTED = "provider_rejected"
    TRANSPORT_ERROR = "transport_error"


@dataclass(slots=True, frozen=True, kw_only=True)
class DeliveryMessage:
    """Immutable message accepted by a channel delivery adapter."""

    publication_id: UUID
    channel: str
    destination_id: str
    rendered_text: str
    correlation_id: str
    disable_web_page_preview: bool = True
    parse_mode: str | None = None
    reference_id: str | None = None


@dataclass(slots=True, frozen=True, kw_only=True)
class DeliveryResult:
    """Safe typed result returned by a channel delivery adapter."""

    outcome: DeliveryOutcome
    destination_id: str
    external_message_id: str | None = None
    provider_error_code: str | None = None
    http_status: int | None = None
    retry_after: timedelta | None = None
    error_category: DeliveryErrorCategory | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if self.outcome is DeliveryOutcome.SUCCESS:
            if self.external_message_id is None or not self.external_message_id.strip():
                msg = "Successful delivery requires an external message ID."
                raise ValueError(msg)
            if self.error_category is not None or self.error_message is not None:
                msg = "Successful delivery must not contain error details."
                raise ValueError(msg)
        elif self.external_message_id is not None:
            msg = "Unconfirmed delivery must not contain an external message ID."
            raise ValueError(msg)
        if self.retry_after is not None:
            if self.retry_after.total_seconds() < 0:
                msg = "Delivery retry duration must not be negative."
                raise ValueError(msg)
            if self.outcome is not DeliveryOutcome.RETRYABLE_FAILURE:
                msg = "Retry duration is valid only for retryable failures."
                raise ValueError(msg)

    @property
    def confirmed(self) -> bool:
        """Return whether provider acceptance was confirmed."""
        return self.outcome is DeliveryOutcome.SUCCESS


@runtime_checkable
class PublicationDeliveryAdapter(Protocol):
    """Port implemented by one outbound publication channel."""

    async def send(self, message: DeliveryMessage) -> DeliveryResult:
        """Attempt one delivery without managing lifecycle or retries."""
        ...
