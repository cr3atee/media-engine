from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from fastapi import Request

from app.api.auth import get_admin_settings
from app.api.dependencies import validate_page_size
from app.api.errors import ApiError
from app.api.pagination import (
    InvalidCursorError,
    encode_cursor,
    make_page_request,
)
from app.repositories.queries.models import CursorPosition, PageRequest


def page_request(
    request: Request,
    *,
    resource: str,
    params: Any,
) -> PageRequest:
    """Build a repository page request from a validated query DTO."""
    configuration = get_admin_settings(request)
    limit = params.limit or configuration.default_page_size
    validate_page_size(request, limit)
    filters = params.model_dump(
        mode="json",
        exclude={"limit", "cursor", "sort", "direction"},
    )
    key = configuration.cursor_signing_key.get_secret_value()
    if not key:
        key = configuration.api_key.get_secret_value()
    try:
        return make_page_request(
            resource=resource,
            limit=limit,
            sort=params.sort,
            direction=params.direction,
            cursor=params.cursor,
            filters=filters,
            signing_key=key,
        )
    except InvalidCursorError as exc:
        raise ApiError(
            422,
            "invalid_cursor",
            "Cursor is invalid or does not match this query.",
        ) from exc


def next_cursor(
    request: Request,
    *,
    position: CursorPosition | None,
) -> str | None:
    """Encode a repository cursor for the response envelope."""
    if position is None:
        return None
    configuration = get_admin_settings(request)
    key = configuration.cursor_signing_key.get_secret_value()
    if not key:
        key = configuration.api_key.get_secret_value()
    return encode_cursor(position, signing_key=key)


def enum_value(value: object) -> str | None:
    """Convert an optional StrEnum-like value to its stable string value."""
    if value is None:
        return None
    raw = getattr(value, "value", value)
    return str(raw)


def query_filters(params: Any) -> Mapping[str, object]:
    """Return serializable filter values for cursor binding."""
    return cast(
        Mapping[str, object],
        params.model_dump(
            mode="json",
            exclude={"limit", "cursor", "sort", "direction"},
        ),
    )
