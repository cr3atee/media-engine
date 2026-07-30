from __future__ import annotations

from time import perf_counter

import structlog

from app.delivery.contracts import (
    DeliveryErrorCategory,
    DeliveryMessage,
    DeliveryOutcome,
    DeliveryResult,
)
from app.telegram.classifier import TelegramDeliveryClassifier
from app.telegram.client import TelegramBotApiClient
from app.telegram.errors import TelegramTransportError
from app.telegram.formatter import TELEGRAM_MESSAGE_LIMIT
from app.telegram.security import (
    is_valid_telegram_destination,
    safe_destination_reference,
)


class TelegramPublicationAdapter:
    """Deliver one plain-text message through the Telegram Bot API."""

    def __init__(
        self,
        client: TelegramBotApiClient,
        *,
        classifier: TelegramDeliveryClassifier | None = None,
        maximum_message_length: int = TELEGRAM_MESSAGE_LIMIT,
    ) -> None:
        if (
            maximum_message_length < 1
            or maximum_message_length > TELEGRAM_MESSAGE_LIMIT
        ):
            msg = "Telegram maximum message length must be between 1 and 4096."
            raise ValueError(msg)
        self._client = client
        self._classifier = classifier or TelegramDeliveryClassifier()
        self._maximum_message_length = maximum_message_length
        self._logger = structlog.get_logger(__name__)

    async def send(self, message: DeliveryMessage) -> DeliveryResult:
        """Perform one validated delivery attempt without retry or persistence."""
        started = perf_counter()
        validation_result = self._validate(message)
        if validation_result is not None:
            self._log(message, validation_result, started=started)
            return validation_result

        try:
            response = await self._client.send_message(
                destination_id=message.destination_id,
                text=message.rendered_text,
                disable_web_page_preview=message.disable_web_page_preview,
            )
        except TelegramTransportError as error:
            result = self._classifier.classify_transport(
                error,
                destination_id=message.destination_id,
            )
        except RuntimeError:
            result = DeliveryResult(
                outcome=DeliveryOutcome.INVALID_REQUEST,
                destination_id=message.destination_id,
                error_category=DeliveryErrorCategory.INVALID_CLIENT_STATE,
                error_message="Telegram client is not available for delivery.",
            )
        else:
            result = self._classifier.classify_response(
                response,
                destination_id=message.destination_id,
            )

        self._log(message, result, started=started)
        return result

    def _validate(self, message: DeliveryMessage) -> DeliveryResult | None:
        if message.channel.strip().lower() != "telegram":
            return _invalid_result(
                message,
                DeliveryErrorCategory.UNSUPPORTED_CHANNEL,
                "Telegram adapter received an unsupported channel.",
            )
        if not is_valid_telegram_destination(message.destination_id):
            return _invalid_result(
                message,
                DeliveryErrorCategory.INVALID_DESTINATION,
                "Telegram destination must be a non-zero numeric chat ID.",
            )
        if message.parse_mode is not None:
            return _invalid_result(
                message,
                DeliveryErrorCategory.INVALID_CONTENT,
                "Telegram MVP delivery supports plain text only.",
            )
        if not message.rendered_text.strip():
            return _invalid_result(
                message,
                DeliveryErrorCategory.INVALID_CONTENT,
                "Telegram message must not be empty.",
            )
        if len(message.rendered_text) > self._maximum_message_length:
            return _invalid_result(
                message,
                DeliveryErrorCategory.MESSAGE_TOO_LONG,
                "Telegram message exceeds the configured length limit.",
            )
        return None

    def _log(
        self,
        message: DeliveryMessage,
        result: DeliveryResult,
        *,
        started: float,
    ) -> None:
        self._logger.info(
            "telegram_delivery_attempt",
            publication_id=str(message.publication_id),
            correlation_id=message.correlation_id,
            destination_reference=safe_destination_reference(message.destination_id),
            outcome=result.outcome.value,
            http_status=result.http_status,
            provider_error_code=result.provider_error_code,
            external_message_id=result.external_message_id,
            duration_ms=round((perf_counter() - started) * 1000, 3),
        )


def _invalid_result(
    message: DeliveryMessage,
    category: DeliveryErrorCategory,
    error_message: str,
) -> DeliveryResult:
    return DeliveryResult(
        outcome=DeliveryOutcome.INVALID_REQUEST,
        destination_id=message.destination_id,
        error_category=category,
        error_message=error_message,
    )
