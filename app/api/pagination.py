from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from app.repositories.queries.models import CursorPosition, PageRequest


class InvalidCursorError(ValueError):
    """Raised when an API cursor is malformed or does not match its query."""


def filter_hash(values: Mapping[str, object]) -> str:
    """Return a deterministic digest of normalized query filters."""
    normalized = json.dumps(
        values,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def make_page_request(
    *,
    resource: str,
    limit: int,
    sort: str,
    direction: str,
    cursor: str | None,
    filters: Mapping[str, object],
    signing_key: str,
) -> PageRequest:
    """Decode and validate a public cursor into a repository page request."""
    expected_hash = filter_hash(filters)
    position = (
        decode_cursor(
            cursor,
            resource=resource,
            sort=sort,
            direction=direction,
            filter_hash=expected_hash,
            signing_key=signing_key,
        )
        if cursor is not None
        else None
    )
    return PageRequest(
        limit=limit,
        sort=sort,
        direction=direction,
        filter_hash=expected_hash,
        cursor=position,
    )


def encode_cursor(position: CursorPosition, *, signing_key: str) -> str:
    """Encode a cursor as signed, URL-safe JSON without executable state."""
    payload = {
        "v": 1,
        "resource": position.resource,
        "sort": position.sort,
        "direction": position.direction,
        "timestamp": position.timestamp.isoformat(),
        "id": str(position.item_id),
        "filter_hash": position.filter_hash,
    }
    body = _encode_payload(payload)
    signature = _signature(body, signing_key)
    return f"{body}.{signature}"


def decode_cursor(
    value: str,
    *,
    resource: str,
    sort: str,
    direction: str,
    filter_hash: str,
    signing_key: str,
) -> CursorPosition:
    """Decode one cursor and reject malformed, stale, or tampered values."""
    try:
        body, signature = value.split(".", 1)
        if not hmac.compare_digest(signature, _signature(body, signing_key)):
            raise InvalidCursorError("Cursor signature is invalid.")
        raw = json.loads(
            base64.urlsafe_b64decode(body.encode("ascii") + b"==="),
        )
        if not isinstance(raw, dict):
            raise InvalidCursorError("Cursor payload must be an object.")
        if (
            raw.get("v") != 1
            or raw.get("resource") != resource
            or raw.get("sort") != sort
            or raw.get("direction") != direction
            or raw.get("filter_hash") != filter_hash
        ):
            raise InvalidCursorError("Cursor does not match this query.")
        timestamp = datetime.fromisoformat(str(raw["timestamp"]))
        if timestamp.tzinfo is None:
            raise InvalidCursorError("Cursor timestamp must include timezone.")
        item_id = UUID(str(raw["id"]))
    except InvalidCursorError:
        raise
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise InvalidCursorError("Cursor is malformed.") from exc
    return CursorPosition(
        resource=resource,
        sort=sort,
        direction=direction,
        timestamp=timestamp,
        item_id=item_id,
        filter_hash=filter_hash,
    )


def _encode_payload(payload: dict[str, object]) -> str:
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(serialized).decode("ascii").rstrip("=")


def _signature(body: str, signing_key: str) -> str:
    key = signing_key.encode("utf-8") or b"mediaengine-read-api-cursor-v1"
    return hmac.new(key, body.encode("ascii"), hashlib.sha256).hexdigest()


def _json_default(value: object) -> object:
    if isinstance(value, (datetime, UUID)):
        return str(value)
    if isinstance(value, set):
        return sorted(value)
    return repr(value)
