from __future__ import annotations

import json
from collections.abc import Callable, Coroutine
from typing import Any
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from app.config.settings import TelegramSettings
from app.delivery.contracts import (
    DeliveryErrorCategory,
    DeliveryMessage,
    DeliveryOutcome,
    DeliveryResult,
    PublicationDeliveryAdapter,
)
from app.telegram.adapter import TelegramPublicationAdapter
from app.telegram.client import TelegramBotApiClient

TOKEN = "123456:OFFLINE_FAKE_TOKEN_DO_NOT_USE"
DESTINATION_ID = "-1001234567890"
PUBLICATION_ID = UUID("00000000-0000-0000-0000-000000001402")
Handler = Callable[[httpx.Request], httpx.Response]


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run one async Telegram test without an async Pytest plugin."""
    import asyncio

    return asyncio.run(awaitable)


def make_message(**overrides: object) -> DeliveryMessage:
    """Create one deterministic delivery message."""
    values: dict[str, object] = {
        "publication_id": PUBLICATION_ID,
        "channel": "telegram",
        "destination_id": DESTINATION_ID,
        "rendered_text": "Minecraft Premium: 790 RUB",
        "correlation_id": "publication-1402",
        "disable_web_page_preview": True,
        "parse_mode": None,
    }
    values.update(overrides)
    return DeliveryMessage(**values)  # type: ignore[arg-type]


def make_client(handler: Handler) -> TelegramBotApiClient:
    """Create an internally owned client with offline transport."""
    return TelegramBotApiClient(
        token=SecretStr(TOKEN),
        api_base_url="https://api.telegram.test",
        transport=httpx.MockTransport(handler),
    )


async def _send_with_handler(
    handler: Handler,
) -> tuple[DeliveryResult, TelegramBotApiClient]:
    client = make_client(handler)
    result = await TelegramPublicationAdapter(client).send(make_message())
    return result, client


async def _success_request_is_minimal_and_result_is_typed() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": 77,
                    "chat": {"id": int(DESTINATION_ID), "type": "channel"},
                },
            },
        )

    client = make_client(handler)
    try:
        result = await TelegramPublicationAdapter(client).send(make_message())
    finally:
        await client.aclose()

    assert len(requests) == 1
    request = requests[0]
    payload = json.loads(request.content)
    assert request.method == "POST"
    assert request.url.path == f"/bot{TOKEN}/sendMessage"
    assert payload == {
        "chat_id": DESTINATION_ID,
        "text": "Minecraft Premium: 790 RUB",
        "link_preview_options": {"is_disabled": True},
    }
    assert "parse_mode" not in payload
    assert TOKEN not in request.content.decode()
    assert result.outcome is DeliveryOutcome.SUCCESS
    assert result.confirmed is True
    assert result.external_message_id == "77"
    assert result.destination_id == DESTINATION_ID
    assert result.http_status == 200


@pytest.mark.parametrize("status", (400, 401, 403, 404))
def test_client_errors_are_permanent(status: int) -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status,
                json={
                    "ok": False,
                    "error_code": status,
                    "description": "Safe rejection",
                },
                request=request,
            )

        result, client = await _send_with_handler(handler)
        await client.aclose()
        assert result.outcome is DeliveryOutcome.PERMANENT_FAILURE
        assert result.provider_error_code == str(status)

    run_async(scenario())


@pytest.mark.parametrize("status", (500, 502, 503))
def test_server_errors_are_retryable(status: int) -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status,
                json={
                    "ok": False,
                    "error_code": status,
                    "description": "Temporary server failure",
                },
                request=request,
            )

        result, client = await _send_with_handler(handler)
        await client.aclose()
        assert result.outcome is DeliveryOutcome.RETRYABLE_FAILURE
        assert result.retry_after is None

    run_async(scenario())


async def _rate_limit_preserves_retry_after_without_retrying() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            429,
            json={
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests",
                "parameters": {"retry_after": 17},
            },
            request=request,
        )

    client = make_client(handler)
    try:
        result = await TelegramPublicationAdapter(client).send(make_message())
    finally:
        await client.aclose()

    assert calls == 1
    assert result.outcome is DeliveryOutcome.RETRYABLE_FAILURE
    assert result.error_category is DeliveryErrorCategory.RATE_LIMITED
    assert result.retry_after is not None
    assert result.retry_after.total_seconds() == 17


@pytest.mark.parametrize(
    ("error_type", "expected_outcome", "expected_category"),
    (
        (
            httpx.ConnectError,
            DeliveryOutcome.RETRYABLE_FAILURE,
            DeliveryErrorCategory.CONNECT_ERROR,
        ),
        (
            httpx.ConnectTimeout,
            DeliveryOutcome.RETRYABLE_FAILURE,
            DeliveryErrorCategory.CONNECT_TIMEOUT,
        ),
        (
            httpx.PoolTimeout,
            DeliveryOutcome.RETRYABLE_FAILURE,
            DeliveryErrorCategory.POOL_TIMEOUT,
        ),
        (
            httpx.WriteTimeout,
            DeliveryOutcome.AMBIGUOUS,
            DeliveryErrorCategory.WRITE_TIMEOUT,
        ),
        (
            httpx.WriteError,
            DeliveryOutcome.AMBIGUOUS,
            DeliveryErrorCategory.WRITE_ERROR,
        ),
        (
            httpx.ReadTimeout,
            DeliveryOutcome.AMBIGUOUS,
            DeliveryErrorCategory.READ_TIMEOUT,
        ),
        (
            httpx.ReadError,
            DeliveryOutcome.AMBIGUOUS,
            DeliveryErrorCategory.READ_ERROR,
        ),
        (
            httpx.RemoteProtocolError,
            DeliveryOutcome.AMBIGUOUS,
            DeliveryErrorCategory.REMOTE_PROTOCOL_ERROR,
        ),
    ),
)
def test_transport_failure_classification_and_token_redaction(
    error_type: type[httpx.RequestError],
    expected_outcome: DeliveryOutcome,
    expected_category: DeliveryErrorCategory,
) -> None:
    async def scenario() -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise error_type(
                f"failure at {request.url} with {TOKEN}",
                request=request,
            )

        client = make_client(handler)
        try:
            result = await TelegramPublicationAdapter(client).send(make_message())
        finally:
            await client.aclose()

        assert calls == 1
        assert result.outcome is expected_outcome
        assert result.error_category is expected_category
        assert TOKEN not in (result.error_message or "")
        assert TOKEN not in repr(result)

    run_async(scenario())


@pytest.mark.parametrize(
    "response",
    (
        httpx.Response(200, content=b"{not-json"),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"ok": True}),
        httpx.Response(200, json={"ok": True, "result": {}}),
        httpx.Response(
            200,
            json={"ok": True, "result": {"message_id": "wrong", "chat": {}}},
        ),
        httpx.Response(
            200,
            json={"ok": True, "result": {"message_id": 1, "chat": {}}},
        ),
    ),
)
def test_malformed_success_responses_are_ambiguous(response: httpx.Response) -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                response.status_code,
                content=response.content,
                headers=response.headers,
                request=request,
            )

        result, client = await _send_with_handler(handler)
        await client.aclose()
        assert result.outcome is DeliveryOutcome.AMBIGUOUS
        assert result.external_message_id is None

    run_async(scenario())


async def _bot_api_200_error_is_classified_and_description_is_redacted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ok": False,
                "error_code": 403,
                "description": f"Forbidden for token {TOKEN}",
            },
            request=request,
        )

    client = make_client(handler)
    try:
        result = await TelegramPublicationAdapter(client).send(make_message())
    finally:
        await client.aclose()

    assert result.outcome is DeliveryOutcome.PERMANENT_FAILURE
    assert result.provider_error_code == "403"
    assert "[REDACTED]" in (result.error_message or "")
    assert TOKEN not in (result.error_message or "")


async def _success_destination_mismatch_is_ambiguous() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {"message_id": 88, "chat": {"id": -100999}},
            },
            request=request,
        )

    client = make_client(handler)
    try:
        result = await TelegramPublicationAdapter(client).send(make_message())
    finally:
        await client.aclose()

    assert result.outcome is DeliveryOutcome.AMBIGUOUS
    assert result.error_category is DeliveryErrorCategory.DESTINATION_MISMATCH
    assert result.external_message_id is None


@pytest.mark.parametrize(
    ("overrides", "category"),
    (
        ({"channel": "email"}, DeliveryErrorCategory.UNSUPPORTED_CHANNEL),
        ({"destination_id": "@channel"}, DeliveryErrorCategory.INVALID_DESTINATION),
        ({"rendered_text": "  "}, DeliveryErrorCategory.INVALID_CONTENT),
        ({"rendered_text": "x" * 4097}, DeliveryErrorCategory.MESSAGE_TOO_LONG),
        ({"parse_mode": "HTML"}, DeliveryErrorCategory.INVALID_CONTENT),
    ),
)
def test_adapter_validation_never_calls_transport(
    overrides: dict[str, object],
    category: DeliveryErrorCategory,
) -> None:
    async def scenario() -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, json={"ok": True}, request=request)

        client = make_client(handler)
        try:
            result = await TelegramPublicationAdapter(client).send(
                make_message(**overrides)
            )
        finally:
            await client.aclose()

        assert calls == 0
        assert result.outcome is DeliveryOutcome.INVALID_REQUEST
        assert result.error_category is category

    run_async(scenario())


async def _internally_owned_client_reuses_transport_and_closes() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {"message_id": calls, "chat": {"id": 123}},
            },
            request=request,
        )

    client = make_client(handler)
    assert client.owns_client is True
    await client.send_message(
        destination_id="123",
        text="one",
        disable_web_page_preview=True,
    )
    await client.send_message(
        destination_id="123",
        text="two",
        disable_web_page_preview=True,
    )
    await client.aclose()

    assert calls == 2
    assert client.is_closed is True
    with pytest.raises(RuntimeError, match="client is closed"):
        await client.send_message(
            destination_id="123",
            text="three",
            disable_web_page_preview=True,
        )


async def _externally_owned_client_is_not_closed() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "ok": True,
                "result": {"message_id": 1, "chat": {"id": 123}},
            },
            request=request,
        )
    )
    external = httpx.AsyncClient(transport=transport)
    client = TelegramBotApiClient(
        token=TOKEN,
        api_base_url="https://api.telegram.test",
        client=external,
    )
    assert client.owns_client is False
    await client.aclose()

    assert client.is_closed is True
    assert external.is_closed is False
    with pytest.raises(RuntimeError, match="client is closed"):
        await client.send_message(
            destination_id="123",
            text="closed wrapper",
            disable_web_page_preview=True,
        )
    await external.aclose()


def test_client_and_settings_representations_redact_token() -> None:
    client = make_client(
        lambda request: httpx.Response(200, json={"ok": False}, request=request)
    )
    settings = TelegramSettings(bot_token=SecretStr(TOKEN))

    assert TOKEN not in repr(client)
    assert TOKEN not in repr(settings)
    assert "**********" in repr(settings)
    run_async(client.aclose())


def test_adapter_satisfies_generic_delivery_protocol() -> None:
    client = make_client(
        lambda request: httpx.Response(200, json={"ok": False}, request=request)
    )
    adapter = TelegramPublicationAdapter(client)

    assert isinstance(adapter, PublicationDeliveryAdapter)
    run_async(client.aclose())


def test_success_request_is_minimal_and_result_is_typed() -> None:
    run_async(_success_request_is_minimal_and_result_is_typed())


def test_rate_limit_preserves_retry_after_without_retrying() -> None:
    run_async(_rate_limit_preserves_retry_after_without_retrying())


def test_bot_api_200_error_is_classified_and_description_is_redacted() -> None:
    run_async(_bot_api_200_error_is_classified_and_description_is_redacted())


def test_success_destination_mismatch_is_ambiguous() -> None:
    run_async(_success_destination_mismatch_is_ambiguous())


def test_internally_owned_client_reuses_transport_and_closes() -> None:
    run_async(_internally_owned_client_reuses_transport_and_closes())


def test_externally_owned_client_is_not_closed() -> None:
    run_async(_externally_owned_client_is_not_closed())
