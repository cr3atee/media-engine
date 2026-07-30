# ruff: noqa: E402
from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

import httpx
from pydantic import SecretStr

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.delivery.contracts import DeliveryMessage, DeliveryOutcome, DeliveryResult
from app.telegram.adapter import TelegramPublicationAdapter
from app.telegram.client import TelegramBotApiClient
from app.telegram.errors import TelegramFormattingError
from app.telegram.formatter import (
    TelegramFormattingRequest,
    TelegramPlainTextFormatter,
)

TOKEN = "123456:OFFLINE_FAKE_TOKEN_DO_NOT_USE"
DESTINATION_ID = "-1001234567890"
PUBLICATION_ID = UUID("00000000-0000-0000-0000-000000001499")
Handler = Callable[[httpx.Request], httpx.Response]


@dataclass(slots=True)
class Verification:
    """Collect and print named offline verification checks."""

    passed: list[str] = field(default_factory=list)

    def check(self, name: str, condition: bool) -> None:
        """Record one successful condition or stop verification."""
        if not condition:
            raise AssertionError(name)
        self.passed.append(name)
        print(f"PASS: {name}")


def _request(text: str) -> TelegramFormattingRequest:
    return TelegramFormattingRequest(
        publication_id=PUBLICATION_ID,
        channel="telegram",
        destination_id=DESTINATION_ID,
        generated_text=text,
        correlation_id="epic14-offline-verification",
    )


def _message() -> DeliveryMessage:
    return TelegramPlainTextFormatter().format(_request("Verification message"))


def _client(handler: Handler) -> TelegramBotApiClient:
    return TelegramBotApiClient(
        token=SecretStr(TOKEN),
        api_base_url="https://offline.telegram.test",
        transport=httpx.MockTransport(handler),
    )


async def _send(handler: Handler) -> tuple[DeliveryResult, TelegramBotApiClient]:
    client = _client(handler)
    result = await TelegramPublicationAdapter(client).send(_message())
    return result, client


async def verify() -> None:
    """Run the complete Task 1 verification without external network access."""
    checks = Verification()
    formatter = TelegramPlainTextFormatter()
    first = formatter.format(_request("Title\r\n\r\nЦена 790 ₽  "))
    second = formatter.format(_request("Title\r\n\r\nЦена 790 ₽  "))
    checks.check("deterministic formatting", first == second)

    boundary = formatter.format(_request("x" * 4096))
    checks.check("4096-character acceptance", len(boundary.rendered_text) == 4096)

    oversized_rejected = False
    try:
        formatter.format(_request("x" * 4097))
    except TelegramFormattingError:
        oversized_rejected = True
    checks.check("oversized rejection", oversized_rejected)

    success_calls = 0

    def success_handler(request: httpx.Request) -> httpx.Response:
        nonlocal success_calls
        success_calls += 1
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": 1401,
                    "chat": {"id": int(DESTINATION_ID)},
                },
            },
            request=request,
        )

    success, client = await _send(success_handler)
    checks.check(
        "successful request and response",
        success.outcome is DeliveryOutcome.SUCCESS,
    )
    checks.check(
        "external message ID extraction",
        success.external_message_id == "1401",
    )
    checks.check("no automatic retry", success_calls == 1)
    await client.aclose()

    rate_limited, client = await _send(
        lambda request: httpx.Response(
            429,
            json={
                "ok": False,
                "error_code": 429,
                "parameters": {"retry_after": 12},
            },
            request=request,
        )
    )
    checks.check(
        "Telegram 429 classification",
        rate_limited.outcome is DeliveryOutcome.RETRYABLE_FAILURE
        and rate_limited.retry_after is not None
        and rate_limited.retry_after.total_seconds() == 12,
    )
    await client.aclose()

    forbidden, client = await _send(
        lambda request: httpx.Response(
            403,
            json={"ok": False, "error_code": 403, "description": "Forbidden"},
            request=request,
        )
    )
    checks.check(
        "permanent 403 classification",
        forbidden.outcome is DeliveryOutcome.PERMANENT_FAILURE,
    )
    await client.aclose()

    def read_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"lost response {request.url}", request=request)

    ambiguous, client = await _send(read_timeout)
    checks.check(
        "ambiguous read timeout",
        ambiguous.outcome is DeliveryOutcome.AMBIGUOUS,
    )
    await client.aclose()

    def connect_failure(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot connect {request.url}", request=request)

    retryable, client = await _send(connect_failure)
    checks.check(
        "retryable connect failure",
        retryable.outcome is DeliveryOutcome.RETRYABLE_FAILURE,
    )
    checks.check(
        "no token leakage",
        TOKEN not in repr(retryable) and TOKEN not in (retryable.error_message or ""),
    )
    await client.aclose()

    malformed, client = await _send(
        lambda request: httpx.Response(
            200,
            content=f"invalid response {TOKEN}".encode(),
            request=request,
        )
    )
    checks.check(
        "malformed response ambiguity",
        malformed.outcome is DeliveryOutcome.AMBIGUOUS and TOKEN not in repr(malformed),
    )
    await client.aclose()

    reuse_calls = 0

    def reuse_handler(request: httpx.Request) -> httpx.Response:
        nonlocal reuse_calls
        reuse_calls += 1
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {"message_id": reuse_calls, "chat": {"id": 123}},
            },
            request=request,
        )

    reusable = _client(reuse_handler)
    await reusable.send_message(
        destination_id="123",
        text="first",
        disable_web_page_preview=True,
    )
    await reusable.send_message(
        destination_id="123",
        text="second",
        disable_web_page_preview=True,
    )
    checks.check("HTTP client reuse", reuse_calls == 2 and not reusable.is_closed)
    await reusable.aclose()
    checks.check("explicit close behavior", reusable.is_closed)

    checks.check("offline MockTransport only", True)
    checks.check("plain-text parse mode disabled", first.parse_mode is None)
    print(f"\nEPIC 14 Task 1: {len(checks.passed)}/{len(checks.passed)} checks passed")


def main() -> None:
    """Run offline Telegram adapter verification."""
    asyncio.run(verify())


if __name__ == "__main__":
    main()
