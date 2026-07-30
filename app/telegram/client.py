from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import quote, urlsplit

import httpx
from pydantic import SecretStr

from app.telegram.errors import (
    TelegramTransportError,
    TelegramTransportFailureKind,
)
from app.telegram.security import sanitize_provider_message


@dataclass(slots=True, frozen=True, kw_only=True)
class TelegramBotApiResponse:
    """Narrow secret-free representation of a Telegram Bot API response."""

    http_status: int
    ok: bool | None
    message_id: int | None = None
    chat_id: int | None = None
    error_code: int | None = None
    description: str | None = None
    retry_after_seconds: int | None = None
    malformed_reason: str | None = None


class TelegramBotApiClient:
    """Single-attempt async client for Telegram's `sendMessage` method."""

    def __init__(
        self,
        *,
        token: SecretStr | str,
        api_base_url: str = "https://api.telegram.org",
        timeout: float | httpx.Timeout = 10.0,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if client is not None and transport is not None:
            msg = "Pass either an external HTTP client or a transport, not both."
            raise ValueError(msg)

        self._token = token if isinstance(token, SecretStr) else SecretStr(token)
        token_value = self._token.get_secret_value()
        if not token_value or token_value != token_value.strip():
            msg = "Telegram bot token must be non-empty and contain no outer spaces."
            raise ValueError(msg)
        if any(character.isspace() for character in token_value):
            msg = "Telegram bot token must not contain whitespace."
            raise ValueError(msg)

        self._api_base_url = _validate_api_base_url(api_base_url)
        self._timeout = timeout
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            transport=transport,
        )
        self._closed = False

    @property
    def owns_client(self) -> bool:
        """Return whether this object owns the underlying HTTP client."""
        return self._owns_client

    @property
    def is_closed(self) -> bool:
        """Return whether this wrapper has been explicitly closed."""
        return self._closed

    async def __aenter__(self) -> TelegramBotApiClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: Any,
    ) -> None:
        await self.aclose()

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(api_base_url={self._api_base_url!r}, "
            f"owns_client={self._owns_client!r}, closed={self._closed!r})"
        )

    async def aclose(self) -> None:
        """Close an owned HTTP client and always close this wrapper."""
        if self._closed:
            return
        self._closed = True
        if self._owns_client:
            await self._client.aclose()

    async def send_message(
        self,
        *,
        destination_id: str,
        text: str,
        disable_web_page_preview: bool,
    ) -> TelegramBotApiResponse:
        """Perform exactly one `sendMessage` request and parse safe fields."""
        if self._closed:
            msg = "Telegram Bot API client is closed."
            raise RuntimeError(msg)

        token = self._token.get_secret_value()
        method_url = f"{self._api_base_url}/bot{quote(token, safe=':')}/sendMessage"
        payload: dict[str, object] = {
            "chat_id": destination_id,
            "text": text,
            "link_preview_options": {
                "is_disabled": disable_web_page_preview,
            },
        }

        try:
            response = await self._client.post(
                method_url,
                json=payload,
                timeout=self._timeout,
            )
        except httpx.ConnectTimeout:
            _raise_transport(TelegramTransportFailureKind.CONNECT_TIMEOUT)
        except httpx.PoolTimeout:
            _raise_transport(TelegramTransportFailureKind.POOL_TIMEOUT)
        except (httpx.ConnectError, httpx.ProxyError):
            _raise_transport(TelegramTransportFailureKind.CONNECT_ERROR)
        except httpx.WriteTimeout:
            _raise_transport(TelegramTransportFailureKind.WRITE_TIMEOUT)
        except httpx.WriteError:
            _raise_transport(TelegramTransportFailureKind.WRITE_ERROR)
        except httpx.ReadTimeout:
            _raise_transport(TelegramTransportFailureKind.READ_TIMEOUT)
        except httpx.ReadError:
            _raise_transport(TelegramTransportFailureKind.READ_ERROR)
        except httpx.RemoteProtocolError:
            _raise_transport(TelegramTransportFailureKind.REMOTE_PROTOCOL_ERROR)
        except (httpx.LocalProtocolError, httpx.UnsupportedProtocol, httpx.InvalidURL):
            _raise_transport(TelegramTransportFailureKind.INVALID_REQUEST)
        except httpx.RequestError:
            _raise_transport(TelegramTransportFailureKind.OTHER)

        return _parse_response(response, token=token)


def _raise_transport(kind: TelegramTransportFailureKind) -> None:
    raise TelegramTransportError(kind) from None


def _validate_api_base_url(value: str) -> str:
    normalized = value.rstrip("/")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        msg = "Telegram API base URL must be an absolute HTTP or HTTPS URL."
        raise ValueError(msg)
    return normalized


def _parse_response(
    response: httpx.Response,
    *,
    token: str,
) -> TelegramBotApiResponse:
    try:
        raw_payload: object = response.json()
    except ValueError:
        return TelegramBotApiResponse(
            http_status=response.status_code,
            ok=None,
            malformed_reason="invalid_json",
        )

    if not isinstance(raw_payload, Mapping):
        return TelegramBotApiResponse(
            http_status=response.status_code,
            ok=None,
            malformed_reason="response_not_object",
        )

    payload = cast("Mapping[str, object]", raw_payload)
    raw_ok = payload.get("ok")
    if not isinstance(raw_ok, bool):
        return TelegramBotApiResponse(
            http_status=response.status_code,
            ok=None,
            malformed_reason="missing_or_invalid_ok",
        )

    if raw_ok:
        return _parse_success(response.status_code, payload)
    return _parse_error(response.status_code, payload, token=token)


def _parse_success(
    http_status: int,
    payload: Mapping[str, object],
) -> TelegramBotApiResponse:
    raw_result = payload.get("result")
    if not isinstance(raw_result, Mapping):
        return TelegramBotApiResponse(
            http_status=http_status,
            ok=True,
            malformed_reason="missing_or_invalid_result",
        )
    result = cast("Mapping[str, object]", raw_result)
    message_id = _strict_int(result.get("message_id"))
    raw_chat = result.get("chat")
    chat_id: int | None = None
    if isinstance(raw_chat, Mapping):
        chat = cast("Mapping[str, object]", raw_chat)
        chat_id = _strict_int(chat.get("id"))

    if message_id is None or message_id <= 0:
        return TelegramBotApiResponse(
            http_status=http_status,
            ok=True,
            malformed_reason="missing_or_invalid_message_id",
        )
    if chat_id is None or chat_id == 0:
        return TelegramBotApiResponse(
            http_status=http_status,
            ok=True,
            message_id=message_id,
            malformed_reason="missing_or_invalid_chat_id",
        )
    return TelegramBotApiResponse(
        http_status=http_status,
        ok=True,
        message_id=message_id,
        chat_id=chat_id,
    )


def _parse_error(
    http_status: int,
    payload: Mapping[str, object],
    *,
    token: str,
) -> TelegramBotApiResponse:
    error_code = _strict_int(payload.get("error_code"))
    raw_description = payload.get("description")
    description = sanitize_provider_message(
        raw_description if isinstance(raw_description, str) else None,
        token=token,
    )
    retry_after_seconds: int | None = None
    raw_parameters = payload.get("parameters")
    if isinstance(raw_parameters, Mapping):
        parameters = cast("Mapping[str, object]", raw_parameters)
        parsed_retry_after = _strict_int(parameters.get("retry_after"))
        if parsed_retry_after is not None and parsed_retry_after >= 0:
            retry_after_seconds = parsed_retry_after

    return TelegramBotApiResponse(
        http_status=http_status,
        ok=False,
        error_code=error_code,
        description=description,
        retry_after_seconds=retry_after_seconds,
    )


def _strict_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
