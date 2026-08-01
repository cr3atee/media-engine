from __future__ import annotations

import re
from typing import cast
from uuid import uuid4

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config.settings import AdminApiSettings

_REQUEST_ID_HEADER = b"x-request-id"
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*\Z")
logger = structlog.get_logger(__name__)


class RequestCorrelationMiddleware:
    """Install a bounded request ID in state, headers, and structlog context."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        settings: AdminApiSettings,
    ) -> None:
        """Create middleware with the configured request-ID bound."""
        self.app = app
        self.settings = settings

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """Process HTTP requests while preserving non-HTTP ASGI traffic."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = self._request_id(scope)
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((_REQUEST_ID_HEADER, request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            structlog.contextvars.clear_contextvars()

    def _request_id(self, scope: Scope) -> str:
        for name, value in scope.get("headers", []):
            if name.lower() != _REQUEST_ID_HEADER:
                continue
            candidate = cast(str, value.decode("latin-1").strip())
            if (
                len(candidate) <= self.settings.request_id_max_length
                and _SAFE_REQUEST_ID.fullmatch(candidate) is not None
            ):
                return candidate
            logger.info("api_request_id_replaced")
            break
        return uuid4().hex
