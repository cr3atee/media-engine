from __future__ import annotations

import ast
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config.settings import AdminApiSettings
from app.main import create_app
from app.repositories.queries.contracts import MarketEventQueryRepository
from app.repositories.queries.models import (
    ContentRead,
    EventQuery,
    EventRead,
    PageRequest,
    PriceDropPayloadRead,
    PublicationRead,
    ReadPage,
    RelatedSummary,
    SnapshotRead,
)
from app.repositories.queries.provider import (
    ReadRepositoryProvider,
    create_memory_read_provider,
)

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _event(number: int) -> EventRead:
    event_id = UUID(int=number)
    previous = SnapshotRead(
        marketplace="playerok",
        external_id=f"offer-{number}",
        collected_at=NOW - timedelta(hours=1),
        price=Decimal("990.00"),
        currency="RUB",
    )
    current = SnapshotRead(
        marketplace="playerok",
        external_id=f"offer-{number}",
        collected_at=NOW,
        price=Decimal("790.00"),
        currency="RUB",
    )
    return EventRead(
        id=event_id,
        identity_key=f"{number:064x}",
        identity_version=1,
        event_type="price_drop",
        marketplace="playerok",
        external_id=f"offer-{number}",
        canonical_product_id=None,
        payload=PriceDropPayloadRead(
            payload_type="price_drop",
            version=1,
            title=f"Minecraft Premium {number}",
            url="https://example.com/item",
            old_price=Decimal("990.00"),
            new_price=Decimal("790.00"),
            currency="RUB",
            absolute_difference=Decimal("200.00"),
            percentage=Decimal("20.202020"),
            previous_snapshot=previous,
            current_snapshot=current,
        ),
        occurred_at=NOW,
        detected_at=NOW + timedelta(minutes=number),
        created_at=NOW + timedelta(minutes=number),
        disposition="active",
        scoring_status="succeeded",
        score=80,
        scoring_attempt_count=1,
        next_retry_at=None,
        error_code=None,
        error_summary=None,
        version=1,
        content_summary=RelatedSummary(count=1, statuses=("generated",)),
        publication_summary=RelatedSummary(count=1, statuses=("pending",)),
    )


def _content(event_id: UUID) -> ContentRead:
    return ContentRead(
        id=uuid4(),
        event_id=event_id,
        parent_content_id=None,
        content_type="telegram_post",
        language="ru",
        origin="ai",
        provider="fake",
        model="deterministic",
        prompt_version="price_drop_v1",
        content_text="Safe plain text",
        generation_status="generated",
        review_status="pending",
        attempt_number=1,
        content_checksum="a" * 64,
        next_retry_at=None,
        error_code=None,
        error_summary=None,
        created_at=NOW,
        updated_at=NOW,
        completed_at=NOW,
        version=1,
        publication_summary=RelatedSummary(count=1, statuses=("pending",)),
    )


def _publication(event_id: UUID, content_id: UUID) -> PublicationRead:
    return PublicationRead(
        id=uuid4(),
        event_id=event_id,
        content_id=content_id,
        channel="telegram",
        destination_reference="0123456789ab",
        status="pending",
        attempt_count=0,
        external_message_id=None,
        scheduled_at=None,
        next_retry_at=None,
        published_at=None,
        error_code=None,
        error_summary=None,
        created_at=NOW,
        updated_at=NOW,
        version=1,
    )


def _client() -> tuple[TestClient, ReadRepositoryProvider]:
    first = _event(1)
    second = _event(2)
    content = _content(first.id)
    publication = _publication(first.id, content.id)
    provider = create_memory_read_provider(
        events=(first, second),
        content=(content,),
        publications=(publication,),
    )

    return _client_for(provider), provider


def _client_for(
    provider: ReadRepositoryProvider,
    *,
    settings: AdminApiSettings | None = None,
    test_mode: bool = False,
    raise_server_exceptions: bool = True,
) -> TestClient:
    @asynccontextmanager
    async def scope() -> AsyncIterator[ReadRepositoryProvider]:
        yield provider

    app = create_app(
        admin_api_settings=settings
        or AdminApiSettings(
            api_enabled=True,
            api_key=SecretStr("test-secret"),
        ),
        read_repository_scope_factory=scope,
    )
    app.state.admin_api_test_mode = test_mode
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def _empty_provider() -> ReadRepositoryProvider:
    return create_memory_read_provider()


class _FailingEventRepository(MarketEventQueryRepository):
    async def list_events(
        self,
        query: EventQuery,
        page: PageRequest,
    ) -> ReadPage[EventRead]:
        raise RuntimeError("database password=do-not-expose")

    async def get_event(self, event_id: UUID) -> EventRead | None:
        raise RuntimeError("database password=do-not-expose")


def test_admin_routes_require_authentication_and_return_correlation() -> None:
    client, _ = _client()
    response = client.get("/api/v1/admin/events")

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "authentication_required"
    assert body["error"]["request_id"] == response.headers["X-Request-ID"]
    assert "test-secret" not in response.text


def test_event_payload_and_related_summaries_are_typed() -> None:
    client, provider = _client()
    event = _event(1)
    response = client.get(
        f"/api/v1/admin/events/{event.id}",
        headers={"X-Admin-API-Key": "test-secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["payload"]["type"] == "price_drop"
    assert body["payload"]["version"] == 1
    assert body["payload"]["old_price"] == "990.00"
    assert body["content_summary"]["count"] == 1
    assert body["publication_summary"]["statuses"] == ["pending"]


def test_keyset_pagination_does_not_duplicate_items() -> None:
    client, _ = _client()
    headers = {"X-Admin-API-Key": "test-secret"}
    first = client.get(
        "/api/v1/admin/events?limit=1",
        headers=headers,
    )
    assert first.status_code == 200
    first_body = first.json()
    assert len(first_body["items"]) == 1
    cursor = first_body["next_cursor"]
    assert isinstance(cursor, str)

    second = client.get(
        f"/api/v1/admin/events?limit=1&cursor={cursor}",
        headers=headers,
    )
    assert second.status_code == 200
    second_body = second.json()
    assert len(second_body["items"]) == 1
    assert first_body["items"][0]["id"] != second_body["items"][0]["id"]


def test_content_and_publication_reads_hide_destination_internals() -> None:
    client, provider = _client()
    headers = {"X-Admin-API-Key": "test-secret"}
    content_response = client.get("/api/v1/admin/content", headers=headers)
    publication_response = client.get(
        "/api/v1/admin/publications",
        headers=headers,
    )

    assert content_response.status_code == 200
    assert content_response.json()["items"][0]["content_text"] == "Safe plain text"
    assert publication_response.status_code == 200
    publication_body = publication_response.json()["items"][0]
    assert publication_body["destination_reference"] == "0123456789ab"
    assert "claim_token" not in publication_body
    assert "telegram" not in publication_body["destination_reference"]
    assert provider is not None


def test_invalid_cursor_and_date_range_use_stable_errors() -> None:
    client, _ = _client()
    headers = {"X-Admin-API-Key": "test-secret"}
    invalid_cursor = client.get(
        "/api/v1/admin/events?cursor=not-a-cursor",
        headers=headers,
    )
    invalid_range = client.get(
        "/api/v1/admin/events"
        "?created_from=2026-08-02T00:00:00Z"
        "&created_to=2026-08-01T00:00:00Z",
        headers=headers,
    )

    assert invalid_cursor.status_code == 422
    assert invalid_cursor.json()["error"]["code"] == "invalid_cursor"
    assert invalid_range.status_code == 422
    assert invalid_range.json()["error"]["code"] == "validation_error"


def test_admin_routes_are_registered_with_expected_methods() -> None:
    client, _ = _client()
    methods_by_path = {
        path: set(route)
        for path, route in client.get(
            "/openapi.json",
            headers={"X-Admin-API-Key": "test-secret"},
        )
        .json()["paths"]
        .items()
    }
    mutation_paths = {
        "/api/v1/admin/content/{content_id}/approve",
        "/api/v1/admin/content/{content_id}/reject",
        "/api/v1/admin/publications/{publication_id}/retry",
        "/api/v1/admin/publications/{publication_id}/cancel",
        "/api/v1/admin/publications/{publication_id}/resolve-ambiguous",
    }

    for path in mutation_paths:
        assert methods_by_path[path] == {"post"}
    assert methods_by_path["/api/v1/admin/dashboard/summary"] == {"get"}
    assert all(
        method.upper() in {"GET", "HEAD", "POST"}
        for methods in methods_by_path.values()
        for method in methods
    )


def test_valid_and_invalid_api_keys_use_constant_time_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client()
    calls: list[tuple[str, str]] = []

    def compare_digest(supplied: str, configured: str) -> bool:
        calls.append((supplied, configured))
        return supplied == configured

    monkeypatch.setattr("app.api.auth.hmac.compare_digest", compare_digest)
    valid = client.get(
        f"/api/v1/admin/events/{UUID(int=1)}",
        headers={"X-Admin-API-Key": "test-secret"},
    )
    invalid = client.get(
        f"/api/v1/admin/events/{UUID(int=1)}",
        headers={"X-Admin-API-Key": "wrong-secret"},
    )

    assert valid.status_code == 200
    assert invalid.status_code == 401
    assert calls == [
        ("test-secret", "test-secret"),
        ("wrong-secret", "test-secret"),
    ]


@pytest.mark.parametrize(
    "settings",
    [
        AdminApiSettings(api_enabled=False, api_key=SecretStr("configured")),
        AdminApiSettings(api_enabled=True, api_key=SecretStr("")),
    ],
)
def test_admin_authentication_fails_closed(settings: AdminApiSettings) -> None:
    client = _client_for(_empty_provider(), settings=settings)

    response = client.get(
        "/api/v1/admin/events",
        headers={"X-Admin-API-Key": "configured"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
    assert "configured" not in response.text


def test_authentication_bypass_requires_both_explicit_guards() -> None:
    provider = _empty_provider()
    disabled_bypass = _client_for(
        provider,
        settings=AdminApiSettings(
            api_enabled=True,
            api_key=SecretStr(""),
            test_bypass_enabled=False,
        ),
        test_mode=True,
    )
    enabled_bypass = _client_for(
        provider,
        settings=AdminApiSettings(
            api_enabled=True,
            api_key=SecretStr(""),
            test_bypass_enabled=True,
        ),
        test_mode=True,
    )

    assert disabled_bypass.get("/api/v1/admin/events").status_code == 401
    assert enabled_bypass.get("/api/v1/admin/events").status_code == 200


def test_openapi_declares_api_key_security_and_can_be_disabled() -> None:
    client, _ = _client()
    unauthenticated = client.get("/openapi.json")
    schema = client.get(
        "/openapi.json",
        headers={"X-Admin-API-Key": "test-secret"},
    ).json()
    security_scheme = schema["components"]["securitySchemes"]["AdminApiKey"]

    assert unauthenticated.status_code == 401
    assert security_scheme["type"] == "apiKey"
    assert security_scheme["in"] == "header"
    assert security_scheme["name"] == "X-Admin-API-Key"
    assert {"AdminApiKey": []} in schema["paths"]["/api/v1/admin/events"]["get"][
        "security"
    ]

    no_docs = _client_for(
        _empty_provider(),
        settings=AdminApiSettings(
            api_key=SecretStr("test-secret"),
            api_docs_enabled=False,
        ),
    )
    assert no_docs.get("/docs").status_code == 404
    assert no_docs.get("/redoc").status_code == 404
    assert no_docs.get("/openapi.json").status_code == 404


def test_request_correlation_accepts_safe_ids_and_replaces_unsafe_ids() -> None:
    client, _ = _client()
    safe = client.get("/health/live", headers={"X-Request-ID": "request-123"})
    unsafe = client.get("/health/live", headers={"X-Request-ID": "bad id"})
    oversized = client.get(
        "/health/live",
        headers={"X-Request-ID": "a" * 129},
    )

    assert safe.headers["X-Request-ID"] == "request-123"
    assert unsafe.headers["X-Request-ID"] != "bad id"
    assert oversized.headers["X-Request-ID"] != "a" * 129
    assert len(unsafe.headers["X-Request-ID"]) == 32


def test_health_exposure_and_readiness_are_sanitized() -> None:
    client, _ = _client()

    live = client.get("/health/live")
    admin_health = client.get("/api/v1/admin/health")

    assert live.status_code == 200
    body = live.json()
    assert body["status"] == "ok"
    assert body["service"] == "mediaengine"
    assert body["database"] == "not_checked"
    assert body["admin_api"] == "configured"
    assert body["migration"] == "not_checked"
    assert body["telegram"] == "disabled"
    assert admin_health.status_code == 401
    assert "postgresql" not in live.text.lower()
    assert "test-secret" not in live.text


def test_dashboard_summary_is_bounded_and_sanitized() -> None:
    event = replace(_event(1), scoring_status="pending")
    content = replace(
        _content(event.id),
        generation_status="generated",
        review_status="approved",
    )
    publication = replace(
        _publication(event.id, content.id),
        status="failed",
        next_retry_at=NOW + timedelta(minutes=10),
    )
    client = _client_for(
        create_memory_read_provider(
            events=(event,),
            content=(content,),
            publications=(publication,),
        )
    )
    cast(Any, client.app).state.dashboard_clock = lambda: NOW + timedelta(hours=1)
    headers = {"X-Admin-API-Key": "test-secret"}

    response = client.get(
        "/api/v1/admin/dashboard/summary",
        headers=headers,
    )
    wide_range = client.get(
        "/api/v1/admin/dashboard/summary",
        params={
            "from": "2026-01-01T00:00:00Z",
            "to": "2026-03-01T00:00:00Z",
        },
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["window"]["boundary"] == "from_inclusive_to_exclusive"
    assert body["total_new_market_events"] == 1
    assert body["events_awaiting_scoring"] == 1
    assert body["approved_content_awaiting_publication"] == 1
    assert body["publications_retryable"] == 1
    assert "test-secret" not in response.text
    assert wide_range.status_code == 422
    assert wide_range.json()["error"]["code"] == "invalid_dashboard_window"


def test_configured_default_and_maximum_page_sizes_are_enforced() -> None:
    provider = create_memory_read_provider(events=(_event(1), _event(2)))
    client = _client_for(
        provider,
        settings=AdminApiSettings(
            api_enabled=True,
            api_key=SecretStr("test-secret"),
            default_page_size=1,
            maximum_page_size=1,
        ),
    )
    headers = {"X-Admin-API-Key": "test-secret"}

    default_page = client.get("/api/v1/admin/events", headers=headers)
    oversized = client.get("/api/v1/admin/events?limit=2", headers=headers)

    assert default_page.status_code == 200
    assert default_page.json()["page_size"] == 1
    assert len(default_page.json()["items"]) == 1
    assert default_page.json()["next_cursor"] is not None
    assert oversized.status_code == 422
    assert oversized.json()["error"]["code"] == "invalid_page_size"


def test_event_filters_sorting_boundaries_and_unicode_search() -> None:
    first = _event(1)
    second = replace(
        _event(2),
        marketplace="ggsel",
        external_id="ggsel-2",
        disposition="ignored",
        scoring_status="failed",
        score=10,
        payload=replace(
            _event(2).payload,
            title="Майнкрафт Премиум",
            url="https://example.com/ggsel/2",
        ),
        content_summary=RelatedSummary(count=0, statuses=()),
        publication_summary=RelatedSummary(count=1, statuses=("ambiguous",)),
    )
    client = _client_for(create_memory_read_provider(events=(first, second)))
    headers = {"X-Admin-API-Key": "test-secret"}

    default_order = client.get("/api/v1/admin/events", headers=headers).json()
    marketplace = client.get(
        "/api/v1/admin/events?marketplace=ggsel",
        headers=headers,
    ).json()
    failure = client.get(
        "/api/v1/admin/events?has_failure=true&ambiguous_only=true",
        headers=headers,
    ).json()
    unicode_search = client.get(
        "/api/v1/admin/events",
        params={"q": "Майнкрафт"},
        headers=headers,
    ).json()
    boundary = client.get(
        "/api/v1/admin/events",
        params={
            "detected_from": second.detected_at.isoformat(),
            "detected_to": second.detected_at.isoformat(),
            "direction": "asc",
        },
        headers=headers,
    ).json()

    assert [item["id"] for item in default_order["items"]] == [
        str(second.id),
        str(first.id),
    ]
    assert [item["id"] for item in marketplace["items"]] == [str(second.id)]
    assert [item["id"] for item in failure["items"]] == [str(second.id)]
    assert unicode_search["items"][0]["payload"]["title"] == "Майнкрафт Премиум"
    assert [item["id"] for item in boundary["items"]] == [str(second.id)]


def test_content_filters_detail_pagination_and_plain_text() -> None:
    first_event = _event(1)
    second_event = _event(2)
    first = replace(
        _content(first_event.id),
        id=UUID(int=101),
        provider="123456:SECRET_TOKEN",
        model="123456:MODEL_TOKEN",
        error_code="provider_error",
        error_summary="provider returned 123456:SECRET_TOKEN",
    )
    second = replace(
        _content(second_event.id),
        id=UUID(int=102),
        content_text="Ошибка генерации <b>не HTML</b>",
        generation_status="failed",
        review_status="rejected",
        attempt_number=2,
        error_code="provider_error",
        error_summary="Safe failure",
        created_at=NOW + timedelta(minutes=2),
        updated_at=NOW + timedelta(minutes=2),
        completed_at=None,
        publication_summary=RelatedSummary(count=0, statuses=()),
    )
    client = _client_for(create_memory_read_provider(content=(first, second)))
    headers = {"X-Admin-API-Key": "test-secret"}

    failed = client.get(
        "/api/v1/admin/content?failed_only=true&review_status=rejected",
        headers=headers,
    ).json()
    event_content = client.get(
        f"/api/v1/admin/events/{second_event.id}/content",
        headers=headers,
    ).json()
    page = client.get("/api/v1/admin/content?limit=1", headers=headers).json()
    detail = client.get(
        f"/api/v1/admin/content/{second.id}",
        headers=headers,
    ).json()

    assert [item["id"] for item in failed["items"]] == [str(second.id)]
    assert [item["id"] for item in event_content["items"]] == [str(second.id)]
    assert page["next_cursor"] is not None
    assert detail["content_text"] == "Ошибка генерации <b>не HTML</b>"
    assert detail["error_summary"] == "Safe failure"
    safe_content = client.get(
        f"/api/v1/admin/content/{first.id}",
        headers=headers,
    ).json()
    assert safe_content["provider"] == "[REDACTED]"
    assert safe_content["model"] == "[REDACTED]"
    assert "SECRET_TOKEN" not in safe_content["error_summary"]


def test_publication_filters_detail_and_safe_operational_fields() -> None:
    event = _event(1)
    content = replace(_content(event.id), id=UUID(int=101))
    pending = replace(
        _publication(event.id, content.id),
        id=UUID(int=201),
    )
    retryable = replace(
        pending,
        id=UUID(int=202),
        status="failed",
        attempt_count=2,
        next_retry_at=NOW + timedelta(minutes=5),
        error_code="telegram_retryable",
        error_summary="Retry later",
        created_at=NOW + timedelta(minutes=1),
        updated_at=NOW + timedelta(minutes=1),
    )
    permanent = replace(
        pending,
        id=UUID(int=203),
        status="failed",
        attempt_count=3,
        error_code="telegram_permanent",
        error_summary="Rejected",
        created_at=NOW + timedelta(minutes=2),
        updated_at=NOW + timedelta(minutes=2),
    )
    published = replace(
        pending,
        id=UUID(int=204),
        status="published",
        attempt_count=1,
        external_message_id="message-42",
        published_at=NOW + timedelta(minutes=3),
        created_at=NOW + timedelta(minutes=3),
        updated_at=NOW + timedelta(minutes=3),
    )
    client = _client_for(
        create_memory_read_provider(
            publications=(pending, retryable, permanent, published),
        )
    )
    headers = {"X-Admin-API-Key": "test-secret"}

    retryable_response = client.get(
        "/api/v1/admin/publications?retryable=true",
        headers=headers,
    ).json()
    permanent_response = client.get(
        "/api/v1/admin/publications?permanent_failure=true&min_attempts=3",
        headers=headers,
    ).json()
    event_publications = client.get(
        f"/api/v1/admin/events/{event.id}/publications",
        headers=headers,
    ).json()
    detail = client.get(
        f"/api/v1/admin/publications/{published.id}",
        headers=headers,
    ).json()

    assert [item["id"] for item in retryable_response["items"]] == [str(retryable.id)]
    assert [item["id"] for item in permanent_response["items"]] == [str(permanent.id)]
    assert len(event_publications["items"]) == 4
    assert detail["external_message_id"] == "message-42"
    assert detail["destination_reference"] == "0123456789ab"
    assert "claim_token" not in detail


@pytest.mark.parametrize(
    ("path", "expected_status", "expected_code"),
    [
        (f"/api/v1/admin/events/{UUID(int=999)}", 404, "not_found"),
        (f"/api/v1/admin/content/{UUID(int=999)}", 404, "not_found"),
        (f"/api/v1/admin/publications/{UUID(int=999)}", 404, "not_found"),
        ("/api/v1/admin/events/not-a-uuid", 422, "validation_error"),
        ("/api/v1/admin/events?sort=score", 422, "validation_error"),
        ("/api/v1/admin/events?limit=0", 422, "validation_error"),
        (
            "/api/v1/admin/events?created_from=2026-08-01T00:00:00",
            422,
            "validation_error",
        ),
    ],
)
def test_stable_resource_and_validation_errors(
    path: str,
    expected_status: int,
    expected_code: str,
) -> None:
    client, _ = _client()
    response = client.get(path, headers={"X-Admin-API-Key": "test-secret"})

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


def test_tampered_or_filter_mismatched_cursor_is_rejected() -> None:
    client, _ = _client()
    headers = {"X-Admin-API-Key": "test-secret"}
    first = client.get("/api/v1/admin/events?limit=1", headers=headers).json()
    cursor = first["next_cursor"]
    assert isinstance(cursor, str)

    tampered = f"{cursor[:-1]}{'0' if cursor[-1] != '0' else '1'}"
    tampered_response = client.get(
        "/api/v1/admin/events",
        params={"limit": 1, "cursor": tampered},
        headers=headers,
    )
    mismatched_response = client.get(
        "/api/v1/admin/events",
        params={"limit": 1, "marketplace": "ggsel", "cursor": cursor},
        headers=headers,
    )

    assert tampered_response.status_code == 422
    assert tampered_response.json()["error"]["code"] == "invalid_cursor"
    assert mismatched_response.status_code == 422
    assert mismatched_response.json()["error"]["code"] == "invalid_cursor"


def test_unexpected_repository_failure_is_sanitized() -> None:
    empty = _empty_provider()
    provider = ReadRepositoryProvider(
        events=_FailingEventRepository(),
        content=empty.content,
        publications=empty.publications,
        dashboard=empty.dashboard,
    )
    client = _client_for(provider, raise_server_exceptions=False)

    response = client.get(
        "/api/v1/admin/events",
        headers={"X-Admin-API-Key": "test-secret"},
    )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "password" not in response.text
    assert "do-not-expose" not in response.text


def test_read_side_layering_has_no_orm_or_delivery_dependencies() -> None:
    paths = (
        Path("app/api/routes/admin_events.py"),
        Path("app/api/routes/admin_content.py"),
        Path("app/api/routes/admin_publications.py"),
        Path("app/api/routes/admin_dashboard.py"),
        Path("app/services/admin_queries.py"),
        Path("app/repositories/queries/contracts.py"),
        Path("app/repositories/queries/models.py"),
    )
    forbidden = (
        "sqlalchemy",
        "app.database.models",
        "app.telegram",
        "app.adapters.telegram",
    )

    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        imports.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        assert not any(
            module.startswith(prefix) for module in imports for prefix in forbidden
        ), path
