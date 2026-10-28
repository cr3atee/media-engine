from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from typing import Any, cast

import httpx
import pytest
from pydantic import SecretStr

from app.core.http_client import HttpClient
from app.parsers.playerok_credentials import (
    PlayerokCredentialError,
    PlayerokSessionCredentials,
)
from app.parsers.playerok_fetcher import (
    PlayerokAccessBlockedError,
    PlayerokFetcher,
    PlayerokInvalidResponseError,
    PlayerokRateLimitedError,
    PlayerokSessionExpiredError,
)

SESSION_SECRET = "session-token-value"
GUARD_SECRET = "guard-cookie-value"


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run one async parser check without an external plugin."""
    return asyncio.run(awaitable)


def make_session() -> PlayerokSessionCredentials:
    """Build deterministic browser-session credentials for transport tests."""
    return PlayerokSessionCredentials.from_secret(
        SecretStr(
            json.dumps(
                {
                    "user_agent": "Playerok verification browser/1.0",
                    "cookies": {
                        "token": SESSION_SECRET,
                        "__ddg3": GUARD_SECRET,
                    },
                }
            )
        )
    )


def items_page(
    item_id: str,
    *,
    end_cursor: str | None,
    has_next_page: bool,
) -> httpx.Response:
    """Build one valid Playerok GraphQL page."""
    return httpx.Response(
        200,
        json={
            "data": {
                "items": {
                    "edges": [
                        {
                            "cursor": f"edge-{item_id}",
                            "node": {
                                "id": item_id,
                                "slug": item_id,
                                "name": f"Offer {item_id}",
                                "price": 100,
                            },
                        }
                    ],
                    "pageInfo": {
                        "endCursor": end_cursor,
                        "hasNextPage": has_next_page,
                    },
                    "totalCount": 2,
                }
            }
        },
    )


def test_session_credentials_are_validated_and_redacted() -> None:
    credentials = make_session()

    assert credentials.user_agent == "Playerok verification browser/1.0"
    assert SESSION_SECRET not in repr(credentials)
    assert GUARD_SECRET not in repr(credentials)

    with pytest.raises(PlayerokCredentialError) as error:
        PlayerokSessionCredentials.from_secret(
            SecretStr('{"user_agent":"Browser","cookies":{"other":"secret"}}')
        )

    assert SESSION_SECRET not in str(error.value)


def test_authenticated_fetcher_injects_browser_session_only_at_transport() -> None:
    client = _QueueHttpClient([items_page("one", end_cursor=None, has_next_page=False)])
    fetcher = PlayerokFetcher(cast(HttpClient, client), session=make_session())

    run_async(fetcher.fetch())

    headers = client.posts[0]["headers"]
    assert isinstance(headers, dict)
    assert headers["User-Agent"] == "Playerok verification browser/1.0"
    assert headers["Cookie"] == (f"token={SESSION_SECRET}; __ddg3={GUARD_SECRET}")
    assert SESSION_SECRET not in repr(fetcher)


def test_fetcher_merges_all_cursor_pages() -> None:
    client = _QueueHttpClient(
        [
            items_page("one", end_cursor="cursor-1", has_next_page=True),
            items_page("two", end_cursor="cursor-2", has_next_page=False),
        ]
    )
    fetcher = PlayerokFetcher(cast(HttpClient, client), max_pages=3)

    raw = run_async(fetcher.fetch(f"{PlayerokFetcher.GRAPHQL_URL}?first=1"))
    payload = json.loads(raw)

    assert [edge["node"]["id"] for edge in payload["data"]["items"]["edges"]] == [
        "one",
        "two",
    ]
    assert client.posts[0]["json"]["variables"]["pagination"]["after"] is None
    assert client.posts[1]["json"]["variables"]["pagination"]["after"] == "cursor-1"
    assert fetcher.pages_fetched == 2


def test_fetcher_rejects_repeated_cursor_instead_of_looping() -> None:
    client = _QueueHttpClient(
        [
            items_page("one", end_cursor="cursor-1", has_next_page=True),
            items_page("two", end_cursor="cursor-1", has_next_page=True),
        ]
    )
    fetcher = PlayerokFetcher(cast(HttpClient, client), max_pages=3)

    with pytest.raises(PlayerokInvalidResponseError, match="repeated cursor"):
        run_async(fetcher.fetch())


@pytest.mark.parametrize(
    ("response", "error_type"),
    [
        (httpx.Response(401, text="unauthorized"), PlayerokSessionExpiredError),
        (httpx.Response(403, text="blocked"), PlayerokAccessBlockedError),
    ],
)
def test_fetcher_classifies_session_failures(
    response: httpx.Response,
    error_type: type[Exception],
) -> None:
    fetcher = PlayerokFetcher(cast(HttpClient, _QueueHttpClient([response])))

    with pytest.raises(error_type):
        run_async(fetcher.fetch())


def test_fetcher_preserves_retry_after_without_response_body() -> None:
    response = httpx.Response(
        429,
        headers={"Retry-After": "17"},
        text=f"echoed {SESSION_SECRET}",
    )
    fetcher = PlayerokFetcher(cast(HttpClient, _QueueHttpClient([response])))

    with pytest.raises(PlayerokRateLimitedError) as error:
        run_async(fetcher.fetch())

    assert error.value.retry_after_seconds == 17
    assert SESSION_SECRET not in str(error.value)
    assert SESSION_SECRET not in (fetcher.last_diagnostic or "")


def test_fetcher_classifies_successful_ddos_challenge_as_blocked() -> None:
    response = httpx.Response(200, text="<html>DDoS-Guard captcha</html>")
    fetcher = PlayerokFetcher(cast(HttpClient, _QueueHttpClient([response])))

    with pytest.raises(PlayerokAccessBlockedError, match="access-protection"):
        run_async(fetcher.fetch())


class _QueueHttpClient:
    """Capture Playerok requests and return queued HTTP responses."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = iter(responses)
        self.posts: list[dict[str, Any]] = []

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        self.posts.append({"url": url, **kwargs})
        return next(self._responses)
