from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import httpx

type QueryParams = Mapping[str, str | int | float | bool | None]
type Headers = Mapping[str, str]


class HttpClient:
    def __init__(
        self,
        *,
        base_url: str = "",
        timeout: float | httpx.Timeout = 10.0,
        max_retries: int = 3,
    ) -> None:
        self._timeout = timeout
        self._max_retries = max(1, min(max_retries, 3))
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def __aenter__(self) -> HttpClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(
        self,
        url: str,
        *,
        params: QueryParams | None = None,
        headers: Headers | None = None,
        timeout: float | httpx.Timeout | None = None,
    ) -> httpx.Response:
        return await self._request(
            "GET",
            url,
            params=params,
            headers=headers,
            timeout=timeout,
        )

    async def post(
        self,
        url: str,
        *,
        content: Any = None,
        json: Any = None,
        params: QueryParams | None = None,
        headers: Headers | None = None,
        timeout: float | httpx.Timeout | None = None,
    ) -> httpx.Response:
        return await self._request(
            "POST",
            url,
            content=content,
            json=json,
            params=params,
            headers=headers,
            timeout=timeout,
        )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        content: Any = None,
        json: Any = None,
        params: QueryParams | None = None,
        headers: Headers | None = None,
        timeout: float | httpx.Timeout | None = None,
    ) -> httpx.Response:
        last_error: httpx.RequestError | None = None
        request_timeout = self._timeout if timeout is None else timeout

        for attempt in range(1, self._max_retries + 1):
            try:
                response = await self._client.request(
                    method=method,
                    url=url,
                    content=content,
                    json=json,
                    params=params,
                    headers=headers,
                    timeout=request_timeout,
                )
            except httpx.RequestError as error:
                last_error = error
                if attempt == self._max_retries:
                    raise
            else:
                if response.status_code < 500 or attempt == self._max_retries:
                    return response

            await asyncio.sleep(2 ** (attempt - 1))

        if last_error is not None:
            raise last_error

        msg = "HTTP request failed without response"
        raise RuntimeError(msg)
