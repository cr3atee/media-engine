"""Readiness HTTP status must reflect only configured, required components."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, cast

import httpx
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.routes import health
from app.config.settings import AdminApiSettings
from app.main import create_app
from scripts.check_api_health import check_api_health

KEY = "offline-health-key"


def _client(*, enabled: bool = True, key: str = KEY) -> TestClient:
    application = create_app(
        admin_api_settings=AdminApiSettings(api_enabled=enabled, api_key=SecretStr(key))
    )

    async def ready() -> bool:
        return True

    application.state.readiness_probe = ready
    return TestClient(application)


@pytest.mark.parametrize(
    ("enabled", "key", "status", "admin"),
    [
        (True, KEY, 200, "configured"),
        (False, "", 200, "disabled"),
        (False, KEY, 200, "disabled"),
        (True, "", 503, "not_configured"),
    ],
)
def test_admin_readiness_respects_explicit_enablement(
    enabled: bool, key: str, status: int, admin: str
) -> None:
    client = _client(enabled=enabled, key=key)
    result = client.get("/health/ready")
    body = result.json()
    assert result.status_code == status
    assert body["status"] == ("ok" if status == 200 else "not_ready")
    assert body["admin_api"] == admin
    assert body["components"]["admin_api"]["required"] is enabled
    assert body["components"]["admin_api"]["status"] == admin
    assert result.headers["Cache-Control"] == "no-store"
    assert KEY not in result.text
    if not enabled:
        assert (
            client.get(
                "/api/v1/admin/readiness", headers={"X-Admin-API-Key": KEY}
            ).status_code
            == 401
        )


@pytest.mark.parametrize("raises", [False, True])
def test_unavailable_database_returns_sanitized_503_without_breaking_liveness(
    raises: bool,
) -> None:
    client = _client(enabled=False, key="")

    async def unavailable() -> bool:
        if raises:
            raise RuntimeError("postgresql://private:secret@private-host/internal")
        return False

    cast(FastAPI, client.app).state.readiness_probe = unavailable
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["database"] == "unavailable"
    assert response.json()["migration"] == "unavailable"
    assert response.headers["Cache-Control"] == "no-store"
    assert not any(
        value in response.text for value in ("private", "secret", "postgresql")
    )
    live = client.get("/health/live")
    assert live.status_code == 200
    assert live.json()["status"] == "ok"
    assert live.json()["database"] == "not_checked"


@pytest.mark.parametrize(
    "field", ["read_repository_scope_factory", "repository_scope_factory"]
)
def test_missing_required_repository_returns_503(field: str) -> None:
    client = _client(enabled=False, key="")
    setattr(cast(FastAPI, client.app).state, field, None)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["repositories"] == "not_configured"
    assert response.json()["components"]["repositories"]["required"] is True


class _Connection:
    """Exercise route/migration decisions without any database connection."""

    def __init__(self, revision: str | None) -> None:
        self._revision = revision

    async def execute(self, statement: object) -> None:
        assert str(statement) == "SELECT 1"

    async def run_sync(self, operation: Callable[[Any], str | None]) -> str | None:
        assert operation is health._current_revision
        return self._revision


class _Engine:
    def __init__(self, revision: str | None) -> None:
        self._revision = revision

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[_Connection]:
        yield _Connection(self._revision)


@pytest.mark.parametrize("migration", ["head", "behind", "missing"])
def test_migration_head_is_required_even_with_admin_disabled(
    monkeypatch: pytest.MonkeyPatch, migration: str
) -> None:
    head = ScriptDirectory.from_config(Config(str(health._ALEMBIC_CONFIG_PATH)))
    revision = (
        head.get_current_head()
        if migration == "head"
        else None
        if migration == "missing"
        else "obsolete_revision"
    )
    monkeypatch.setattr(health, "engine", _Engine(revision))
    client = _client(enabled=False, key="")
    del cast(FastAPI, client.app).state.readiness_probe
    result = client.get("/health/ready")
    assert result.status_code == (200 if migration == "head" else 503)
    assert result.json()["database"] == "ok"
    assert result.json()["migration"] == ("head" if migration == "head" else "behind")


@pytest.mark.parametrize("ready", [False, True])
def test_admin_alias_keeps_authentication_and_same_readiness_result(
    ready: bool,
) -> None:
    client = _client()

    async def probe() -> bool:
        return ready

    cast(FastAPI, client.app).state.readiness_probe = probe
    public = client.get("/health/ready")
    protected = client.get("/api/v1/admin/readiness", headers={"X-Admin-API-Key": KEY})
    assert protected.status_code == public.status_code == (200 if ready else 503)
    assert protected.json() == public.json()
    assert protected.headers["Cache-Control"] == "no-store"
    assert client.get("/api/v1/admin/readiness").status_code == 401


def test_openapi_declares_readiness_503_with_existing_response_schema() -> None:
    response = _client().get("/openapi.json", headers={"X-Admin-API-Key": KEY})
    assert response.status_code == 200
    paths = response.json()["paths"]
    for path in ("/health/ready", "/api/v1/admin/readiness"):
        schema = paths[path]["get"]["responses"]["503"]["content"]["application/json"]
        assert schema["schema"]["$ref"].endswith("/HealthResponse")


@pytest.mark.parametrize("ready", [False, True])
def test_existing_orchestrator_checker_accepts_only_ready_status(
    monkeypatch: pytest.MonkeyPatch, ready: bool
) -> None:
    client = _client(enabled=False, key="")

    async def probe() -> bool:
        return ready

    cast(FastAPI, client.app).state.readiness_probe = probe
    response = client.get("/health/ready")

    def get(url: str, *, timeout: float) -> httpx.Response:
        assert url == "http://127.0.0.1/health/ready" and timeout == 1
        return cast(httpx.Response, response)

    monkeypatch.setattr("scripts.check_api_health.httpx.get", get)
    if ready:
        check_api_health("http://127.0.0.1/health/ready", timeout_seconds=1)
    else:
        with pytest.raises(RuntimeError, match="API readiness failed"):
            check_api_health("http://127.0.0.1/health/ready", timeout_seconds=1)
