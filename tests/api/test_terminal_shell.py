from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config.settings import AdminApiSettings
from app.main import create_app


def _client() -> TestClient:
    app = create_app(
        admin_api_settings=AdminApiSettings(
            api_enabled=True,
            api_key=SecretStr("test-secret"),
        ),
        public_read_repository_scope_factory=None,
    )
    return TestClient(app)


def test_market_terminal_shell_is_served() -> None:
    client = _client()

    response = client.get("/terminal")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Market Terminal" in response.text
    assert "/terminal/styles.css" in response.text
    assert "/terminal/app.js" in response.text
    assert 'id="productCount"' in response.text
    assert 'id="offerCount"' in response.text
    assert 'id="categoryCount"' in response.text
    assert 'id="dropCount"' in response.text


def test_market_terminal_static_assets_are_served() -> None:
    client = _client()

    styles = client.get("/terminal/styles.css")
    script = client.get("/terminal/app.js")

    assert styles.status_code == 200
    assert styles.headers["content-type"].startswith("text/css")
    assert "backdrop-filter" in styles.text
    assert script.status_code == 200
    assert script.headers["content-type"].startswith("application/javascript")
    assert 'const api = "/api/v1/public";' in script.text
    assert "function updateSummary()" in script.text
    assert "function setDashboardBusy(isBusy)" in script.text
