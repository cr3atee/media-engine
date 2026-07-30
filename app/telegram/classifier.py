from __future__ import annotations

from datetime import timedelta

from app.delivery.contracts import (
    DeliveryErrorCategory,
    DeliveryOutcome,
    DeliveryResult,
)
from app.telegram.client import TelegramBotApiResponse
from app.telegram.errors import TelegramTransportError, TelegramTransportFailureKind


class TelegramDeliveryClassifier:
    """Map Telegram responses and transport failures to delivery outcomes."""

    def classify_response(
        self,
        response: TelegramBotApiResponse,
        *,
        destination_id: str,
    ) -> DeliveryResult:
        """Classify one completed HTTP response conservatively."""
        provider_code = (
            str(response.error_code) if response.error_code is not None else None
        )
        retry_after = (
            timedelta(seconds=response.retry_after_seconds)
            if response.retry_after_seconds is not None
            else None
        )

        if response.http_status == 429 or response.error_code == 429:
            return DeliveryResult(
                outcome=DeliveryOutcome.RETRYABLE_FAILURE,
                destination_id=destination_id,
                provider_error_code=provider_code or "429",
                http_status=response.http_status,
                retry_after=retry_after,
                error_category=DeliveryErrorCategory.RATE_LIMITED,
                error_message=response.description or "Telegram rate limit exceeded.",
            )

        if response.http_status >= 500 or (
            response.error_code is not None and response.error_code >= 500
        ):
            return DeliveryResult(
                outcome=DeliveryOutcome.RETRYABLE_FAILURE,
                destination_id=destination_id,
                provider_error_code=provider_code,
                http_status=response.http_status,
                error_category=DeliveryErrorCategory.PROVIDER_SERVER_ERROR,
                error_message=response.description or "Telegram server error.",
            )

        if 400 <= response.http_status < 500:
            return DeliveryResult(
                outcome=DeliveryOutcome.PERMANENT_FAILURE,
                destination_id=destination_id,
                provider_error_code=provider_code or str(response.http_status),
                http_status=response.http_status,
                error_category=DeliveryErrorCategory.PROVIDER_CLIENT_ERROR,
                error_message=response.description or "Telegram rejected the request.",
            )

        if not 200 <= response.http_status < 300:
            return DeliveryResult(
                outcome=DeliveryOutcome.PERMANENT_FAILURE,
                destination_id=destination_id,
                provider_error_code=provider_code,
                http_status=response.http_status,
                error_category=DeliveryErrorCategory.PROVIDER_CLIENT_ERROR,
                error_message="Telegram returned an unsupported HTTP status.",
            )

        if response.ok is False:
            return DeliveryResult(
                outcome=DeliveryOutcome.PERMANENT_FAILURE,
                destination_id=destination_id,
                provider_error_code=provider_code,
                http_status=response.http_status,
                error_category=DeliveryErrorCategory.PROVIDER_REJECTED,
                error_message=response.description or "Telegram rejected the request.",
            )

        if response.ok is not True or response.malformed_reason is not None:
            return DeliveryResult(
                outcome=DeliveryOutcome.AMBIGUOUS,
                destination_id=destination_id,
                http_status=response.http_status,
                error_category=DeliveryErrorCategory.MALFORMED_RESPONSE,
                error_message="Telegram response was incomplete or malformed.",
            )

        if response.message_id is None or response.chat_id is None:
            return DeliveryResult(
                outcome=DeliveryOutcome.AMBIGUOUS,
                destination_id=destination_id,
                http_status=response.http_status,
                error_category=DeliveryErrorCategory.MALFORMED_RESPONSE,
                error_message="Telegram success response lacked required identifiers.",
            )

        if str(response.chat_id) != destination_id:
            return DeliveryResult(
                outcome=DeliveryOutcome.AMBIGUOUS,
                destination_id=destination_id,
                http_status=response.http_status,
                error_category=DeliveryErrorCategory.DESTINATION_MISMATCH,
                error_message=(
                    "Telegram response destination did not match the request."
                ),
            )

        return DeliveryResult(
            outcome=DeliveryOutcome.SUCCESS,
            destination_id=destination_id,
            external_message_id=str(response.message_id),
            http_status=response.http_status,
        )

    def classify_transport(
        self,
        error: TelegramTransportError,
        *,
        destination_id: str,
    ) -> DeliveryResult:
        """Classify one secret-free transport failure."""
        category = _TRANSPORT_CATEGORIES[error.kind]
        if error.kind in _RETRYABLE_TRANSPORT_FAILURES:
            outcome = DeliveryOutcome.RETRYABLE_FAILURE
        elif error.kind is TelegramTransportFailureKind.INVALID_REQUEST:
            outcome = DeliveryOutcome.INVALID_REQUEST
        else:
            outcome = DeliveryOutcome.AMBIGUOUS
        return DeliveryResult(
            outcome=outcome,
            destination_id=destination_id,
            error_category=category,
            error_message=str(error),
        )


_RETRYABLE_TRANSPORT_FAILURES = frozenset(
    {
        TelegramTransportFailureKind.CONNECT_TIMEOUT,
        TelegramTransportFailureKind.CONNECT_ERROR,
        TelegramTransportFailureKind.POOL_TIMEOUT,
    }
)

_TRANSPORT_CATEGORIES = {
    TelegramTransportFailureKind.CONNECT_TIMEOUT: (
        DeliveryErrorCategory.CONNECT_TIMEOUT
    ),
    TelegramTransportFailureKind.CONNECT_ERROR: DeliveryErrorCategory.CONNECT_ERROR,
    TelegramTransportFailureKind.POOL_TIMEOUT: DeliveryErrorCategory.POOL_TIMEOUT,
    TelegramTransportFailureKind.WRITE_TIMEOUT: DeliveryErrorCategory.WRITE_TIMEOUT,
    TelegramTransportFailureKind.WRITE_ERROR: DeliveryErrorCategory.WRITE_ERROR,
    TelegramTransportFailureKind.READ_TIMEOUT: DeliveryErrorCategory.READ_TIMEOUT,
    TelegramTransportFailureKind.READ_ERROR: DeliveryErrorCategory.READ_ERROR,
    TelegramTransportFailureKind.REMOTE_PROTOCOL_ERROR: (
        DeliveryErrorCategory.REMOTE_PROTOCOL_ERROR
    ),
    TelegramTransportFailureKind.INVALID_REQUEST: (
        DeliveryErrorCategory.INVALID_CLIENT_STATE
    ),
    TelegramTransportFailureKind.OTHER: DeliveryErrorCategory.TRANSPORT_ERROR,
}
