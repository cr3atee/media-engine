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
    assert 'id="marketplaceFilter"' in response.text
    assert 'id="sortFilter"' in response.text
    assert 'id="minPriceInput"' in response.text
    assert 'id="maxPriceInput"' in response.text


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
    assert 'query.set("marketplace", marketplace);' in script.text
    assert 'query.set("category", state.selectedCategoryName);' in script.text
    assert 'query.set("min_price", minPrice);' in script.text
    assert 'query.set("max_price", maxPrice);' in script.text
    assert 'query.set("sort", sort);' in script.text
    assert "function renderCategories(categories)" in script.text
    assert "function selectCategory(category)" in script.text
    assert "function priceRangeIsValid()" in script.text
    assert 'window.addEventListener("popstate"' in script.text
    assert "function restoreLocationState()" in script.text
    assert "function syncLocationState(mode)" in script.text
    assert 'syncLocationState("push");' in script.text
    assert "function renderHistorySeries(currency, points)" in script.text
    assert "const seriesByCurrency = new Map();" in script.text
    assert "function renderPriceChanges(changes)" in script.text
    assert "void selectProduct(change.product_id);" in script.text
