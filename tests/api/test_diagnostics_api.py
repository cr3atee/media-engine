"""Diagnostic intake is sanitized and journal reads require product admin."""

from typing import cast
from uuid import UUID

import pytest
from fastapi import FastAPI, Request

from app.repositories.provider import create_memory_provider
from app.services.product_roles import ProductRoleService
from app.services.repository_scope import create_memory_repository_scope
from tests.api.test_seller_auth_api import PASSWORD, USER_ID, _client, _seed_identity
from tests.repositories.contracts.factories import run_async


def test_frontend_report_and_product_admin_journal() -> None:
    provider = create_memory_provider()
    run_async(_seed_identity(provider))
    client = _client(provider)
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "seller@example.com", "password": PASSWORD},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    report = {
        "kind": "error",
        "page": "review",
        "component": "shell",
        "action": "render",
        "request_id": "browser-request",
    }

    accepted = client.post("/api/v1/diagnostics/frontend", headers=headers, json=report)
    denied = client.get("/api/v1/platform/diagnostics", headers=headers)
    unauthenticated = client.get("/api/v1/platform/diagnostics")

    assert accepted.status_code == 202
    assert accepted.json()["status"] == "accepted"
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "product_admin_required"
    assert unauthenticated.status_code == 401
    service = ProductRoleService(create_memory_repository_scope(provider))
    run_async(
        service.bootstrap(
            user_id=USER_ID,
            expected_version=1,
            reason="Test operator",
            idempotency_key="bootstrap-diagnostics",
        )
    )

    repeated = client.post("/api/v1/diagnostics/frontend", headers=headers, json=report)
    listing = client.get("/api/v1/platform/diagnostics", headers=headers)

    assert repeated.status_code == 202
    assert repeated.json()["incident_id"] == accepted.json()["incident_id"]
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    incident = listing.json()["items"][0]
    assert incident["occurrence_count"] == 2
    assert incident["user_id"] == str(USER_ID)
    assert incident["route"] == "/terminal/review"
    assert "message" not in incident and "password" not in listing.text.lower()
    detail = client.get(
        f"/api/v1/platform/diagnostics/{incident['id']}", headers=headers
    )
    assert detail.status_code == 200 and detail.json() == incident


def test_frontend_report_rejects_unbounded_or_secret_fields() -> None:
    provider = create_memory_provider()
    run_async(_seed_identity(provider))
    client = _client(provider)
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "seller@example.com", "password": PASSWORD},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    response = client.post(
        "/api/v1/diagnostics/frontend",
        headers=headers,
        json={
            "kind": "error",
            "page": "review",
            "component": "shell",
            "action": "render",
            "message": "password=secret",
        },
    )

    assert response.status_code == 422
    assert "password=secret" not in response.text


def test_unexpected_api_error_is_persisted_without_exception_message() -> None:
    provider = create_memory_provider()
    client = _client(provider)
    application = cast(FastAPI, client.app)

    @application.get("/api/v1/diagnostic-test-crash")
    async def crash(request: Request) -> None:
        del request
        raise RuntimeError("password=never-store bearer=secret")

    response = client.get(
        "/api/v1/diagnostic-test-crash",
        headers={"X-Request-ID": "diagnostic-request"},
    )

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["request_id"] == "diagnostic-request"
    incident_id = UUID(body["error"]["details"]["incident_id"])
    incident = run_async(provider.diagnostic_incidents.get_by_id(incident_id))
    assert incident is not None
    assert incident.error_type == "RuntimeError"
    assert incident.route == "/api/v1/diagnostic-test-crash"
    assert "never-store" not in response.text
    assert "secret" not in response.text


def test_unexpected_terminal_error_uses_safe_html_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import terminal

    provider = create_memory_provider()
    client = _client(provider)
    original = terminal._read_asset

    def fail_only_catalog(name: str) -> str:
        if name == "index.html":
            raise RuntimeError("cookie=never-store")
        return original(name)

    monkeypatch.setattr(terminal, "_read_asset", fail_only_catalog)
    response = client.get("/terminal", headers={"X-Request-ID": "terminal-failure"})

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("text/html")
    assert "Не удалось открыть страницу" in response.text
    assert "terminal-failure" in response.text
    assert "cookie=never-store" not in response.text
