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

    for path in ("/terminal", "/terminal/"):
        response = client.get(path)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "default-src 'self'" in response.headers["content-security-policy"]
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert response.headers["permissions-policy"] == (
            "camera=(), geolocation=(), microphone=()"
        )
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
        assert 'aria-labelledby="detailTitle"' in response.text
        assert 'aria-busy="false"' in response.text


def test_market_terminal_static_assets_are_served() -> None:
    client = _client()

    styles = client.get("/terminal/styles.css")
    script = client.get("/terminal/app.js")

    assert styles.status_code == 200
    assert styles.headers["content-type"].startswith("text/css")
    assert styles.headers["x-content-type-options"] == "nosniff"
    assert "backdrop-filter" in styles.text
    assert script.status_code == 200
    assert script.headers["content-type"].startswith("application/javascript")
    assert script.headers["x-content-type-options"] == "nosniff"
    assert 'const api = "/api/v1/public";' in script.text
    assert "const requestTimeoutMs = 15_000;" in script.text
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
    assert "function moneyHtml(value, currency)" in script.text
    assert 'rel="noopener noreferrer"' in script.text
    assert "catalogRequestVersion: 0" in script.text
    assert "function beginCatalogRequest()" in script.text
    assert "function isCurrentCatalogRequest(requestVersion)" in script.text
    assert "detailRequestVersion: 0" in script.text
    assert "function isCurrentDetailRequest(requestVersion, productId)" in script.text
    assert "function setProductDetailsBusy(isBusy)" in script.text
    assert "await Promise.allSettled(" in script.text
    assert "function renderDetailSummary(result, productId)" in script.text
    assert (
        "function renderDetailResult(result, target, renderer, unavailableLabel)"
        in script.text
    )
    assert "const controller = new AbortController();" in script.text
    assert "signal: controller.signal" in script.text
    assert "window.clearTimeout(timeoutId);" in script.text
    assert "Request timed out. Please try again." in script.text
