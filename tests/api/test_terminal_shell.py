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
        assert "style-src 'self'" in response.headers["content-security-policy"]
        assert "'unsafe-inline'" not in response.headers["content-security-policy"]
        assert response.headers["permissions-policy"] == (
            "camera=(), geolocation=(), microphone=()"
        )
        assert '<html lang="ru">' in response.text
        assert '<body class="terminal-page">' in response.text
        assert "Market Terminal" in response.text
        assert "Ваш следующий мир." in response.text
        assert "Сравните предложения площадок" in response.text
        assert 'id="catalogView"' in response.text
        assert 'id="backToCatalog"' in response.text
        assert 'href="/terminal/review">Кабинет продавца</a>' in response.text
        assert 'aria-label="Найти товары"' in response.text
        assert "Find the best marketplace price" not in response.text
        assert "/terminal/catalog.css" in response.text
        assert "/terminal/preview/preview.css" in response.text
        assert "/terminal/app.js" in response.text
        assert 'id="productCount"' in response.text
        assert 'id="catalogPagination"' in response.text
        assert 'id="loadMoreButton"' in response.text
        assert 'aria-controls="productGrid"' in response.text
        assert 'id="filtersButton"' in response.text
        assert 'id="catalogFilters"' in response.text
        assert 'id="dropCount"' in response.text
        assert 'id="marketplaceFilter"' in response.text
        assert 'id="sortFilter"' in response.text
        assert 'id="minPriceInput"' in response.text
        assert 'id="maxPriceInput"' in response.text
        assert 'class="skip" href="#main"' in response.text
        assert 'id="products"' in response.text
        assert 'aria-labelledby="catalogTitle"' in response.text
        assert 'aria-labelledby="detailTitle"' in response.text
        assert 'id="detailTitle" tabindex="-1"' in response.text
        assert 'aria-busy="false"' in response.text
        assert 'id="apiStatus"' in response.text
        assert 'role="status"' in response.text
        assert 'aria-atomic="true"' in response.text
        assert 'id="categoryList"' in response.text
        assert 'id="changeList"' in response.text
        assert 'aria-labelledby="offerListTitle"' in response.text
        assert 'aria-labelledby="comparisonTitle"' in response.text
        assert 'aria-labelledby="historyTitle"' in response.text
        assert response.text.count('aria-live="polite"') == 8
        assert 'id="previewTools"' not in response.text
        assert 'id="roleSelect"' not in response.text
        assert 'type="module" src="/terminal/app.js"' in response.text


def test_market_terminal_static_assets_are_served() -> None:
    client = _client()

    styles = client.get("/terminal/styles.css")
    script = client.get("/terminal/app.js")

    assert styles.status_code == 200
    assert styles.headers["content-type"].startswith("text/css")
    assert styles.headers["x-content-type-options"] == "nosniff"
    assert "backdrop-filter" not in styles.text
    assert "linear-gradient" not in styles.text
    assert "radial-gradient" not in styles.text
    assert "border-radius: 999px" not in styles.text
    assert 'class="glass"' not in client.get("/terminal").text
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
    assert 'query.set("cursor", cursor);' in script.text
    assert "state.nextCatalogCursor = payload.next_cursor ?? null;" in script.text
    assert "function loadMoreProducts()" in script.text
    assert "function appendUniqueProducts(current, incoming)" in script.text
    assert "function updateCatalogPagination()" in script.text
    assert "function renderCategories(categories)" in script.text
    assert "function selectCategory(category)" in script.text
    assert "function priceRangeIsValid()" in script.text
    assert 'window.addEventListener("popstate"' in script.text
    assert "function restoreLocationState()" in script.text
    assert "function syncLocationState(mode)" in script.text
    assert 'syncLocationState("push");' in script.text
    assert "function renderHistorySeries(currency, points)" in script.text
    assert "function historyHeightClass(price, lowest, range)" in script.text
    assert 'style="height:' not in script.text
    assert ".history-height-100" in styles.text
    assert "const seriesByCurrency = new Map();" in script.text
    assert "function renderPriceChanges(changes)" in script.text
    assert "void selectProduct(change.product_id);" in script.text
    assert "elements.detailTitle.focus({ preventScroll: true });" in script.text
    assert "function moneyHtml(value, currency)" in script.text
    assert 'rel="noopener noreferrer"' in script.text
    assert "catalogRequestVersion: 0" in script.text
    assert "function beginCatalogRequest()" in script.text
    assert "function isCurrentCatalogRequest(requestVersion)" in script.text
    assert "categoryRequestVersion: 0" in script.text
    assert "function beginCategoryRequest()" in script.text
    assert "function isCurrentCategoryRequest(requestVersion)" in script.text
    assert "priceChangeRequestVersion: 0" in script.text
    assert "function beginPriceChangeRequest()" in script.text
    assert "function isCurrentPriceChangeRequest(requestVersion)" in script.text
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
    assert "Время ожидания истекло. Попробуйте ещё раз." in script.text
    assert "function parsePublicJson(text, contentType)" in script.text
    assert "function isJsonContentType(contentType)" in script.text
    assert "function publicApiErrorMessage(body, status)" in script.text
    assert "Сервис вернул некорректный ответ." in script.text
    assert "function comparisonStatusLabel(status)" in script.text
    assert 'complete: "Сравнение готово"' in script.text
    assert "function differenceReasonLabel(reason)" in script.text
    assert "function countLabel(value, one, few, many)" in script.text
    assert 'new Intl.DateTimeFormat("ru-RU"' in script.text
    assert '"No products found"' not in script.text
    assert '"Loading offers..."' not in script.text
    assert "response.statusText" not in script.text
    assert ".skip-link:focus" in styles.text
    assert "#detailTitle:focus-visible" in styles.text


def test_working_catalog_reuses_preview_assets_without_mock_actions() -> None:
    """Keep shared artwork local and demonstration tools out of the live shell."""
    client = _client()
    styles = client.get("/terminal/catalog.css")
    presentation = client.get("/terminal/preview/presentation.js")
    script = client.get("/terminal/app.js").text

    assert styles.status_code == 200
    assert styles.headers["content-type"].startswith("text/css")
    assert ".catalog-filters" in styles.text
    assert ".history-height-100" in styles.text
    assert presentation.status_code == 200
    assert "export function offerFootprint" in presentation.text
    assert "export function handleImageError" in presentation.text
    assert 'from "/terminal/preview/presentation.js"' in script
    assert 'comparison.status === "currency_mismatch"' in script
    assert 'method: "POST"' not in script
    assert "previewRole" not in script
    assert "localStorage" not in script


def test_market_terminal_catalog_review_workspace_is_served() -> None:
    client = _client()

    for path in ("/terminal/review", "/terminal/review/"):
        response = client.get(path)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "default-src 'self'" in response.headers["content-security-policy"]
        assert "style-src 'self'" in response.headers["content-security-policy"]
        assert "'unsafe-inline'" not in response.headers["content-security-policy"]
        assert (
            '<span>market<span class="brand-second">terminal</span></span>'
            in response.text
        )
        assert 'class="header"' in response.text
        assert 'class="cabinet-nav"' in response.text
        assert "Личный кабинет" in response.text
        assert 'class="review-page"' in response.text
        assert " glass" not in response.text
        assert 'id="loginForm"' in response.text
        assert 'id="loginButton" type="submit" disabled' in response.text
        assert 'autocomplete="username"' in response.text
        assert 'autocomplete="current-password"' in response.text
        assert 'id="tenantSelect"' in response.text
        assert 'id="offerCount"' in response.text
        assert 'id="linkedOfferCount"' in response.text
        assert 'id="catalogProgress"' in response.text
        assert 'id="marketplaceProgress"' in response.text
        assert 'id="queueSearchInput"' in response.text
        assert 'id="queueMarketplaceFilter"' in response.text
        assert 'id="candidatePagination"' in response.text
        assert 'id="proposalPagination"' in response.text
        assert 'id="reviewCandidates"' in response.text
        assert 'id="productProposals"' in response.text
        assert 'aria-busy="false"' in response.text
        assert "/terminal/preview/preview.css" in response.text
        assert "/terminal/review.css" in response.text
        assert "/terminal/review.js" in response.text


def test_market_terminal_catalog_review_assets_are_served() -> None:
    client = _client()

    styles = client.get("/terminal/review.css")
    script = client.get("/terminal/review.js")

    assert styles.status_code == 200
    assert styles.headers["content-type"].startswith("text/css")
    assert styles.headers["x-content-type-options"] == "nosniff"
    assert ".review-columns" in styles.text
    assert ".review-card" in styles.text
    assert ".queue-toolbar" in styles.text
    assert ".queue-pagination" in styles.text
    assert ".decision-details" in styles.text
    assert ".action-button.resolve" in styles.text
    assert ".cabinet-nav" in styles.text
    assert ".topbar" not in styles.text
    assert ".brand-mark" not in styles.text
    assert ".review-shell { width:" not in styles.text
    assert "@media (max-width: 560px)" in styles.text
    assert "linear-gradient" not in styles.text
    assert "border-radius: 999px" not in styles.text
    assert 'card.className = "marketplace-progress-card";' in script.text

    assert script.status_code == 200
    assert script.headers["content-type"].startswith("application/javascript")
    assert script.headers["x-content-type-options"] == "nosniff"
    assert 'const api = "/api/v1";' in script.text
    assert 'browserAuth("refresh")' in script.text
    assert 'browserAuth("logout")' in script.text
    assert "requestJson(`/auth/browser/${path}`" in script.text
    assert 'requestJson("/me")' in script.text
    assert "/catalog/onboarding-workspace?limit=100" in script.text
    assert "function renderOnboardingSummary(summary)" in script.text
    assert "function marketplaceProgressCard(summary)" in script.text
    assert "function renderQueues()" in script.text
    assert "function queueItemMatches(item)" in script.text
    assert "function paginate(items, requestedPage, pageSize)" in script.text
    assert "const proposalPageSize = 9;" in script.text
    assert "${externalLinkHtml(proposal.offer_url)}" in script.text
    assert "${externalLinkHtml(candidate.offer_url)}" in script.text
    assert "card.dataset.canonicalProductName" in script.text
    assert "Связать объявление с каноническим товаром" in script.text
    assert "Для нового товара поле необязательно" in script.text
    assert "PC, Java + Bedrock, ключ Microsoft, GLOBAL" in script.text
    assert "`/catalog/reviews/${endpoint}`" in script.text
    assert "let endpoint = `${base}/confirm`;" in script.text
    assert "endpoint = `${base}/resolve-existing`;" in script.text
    assert 'headers: { "Idempotency-Key": idempotencyKey }' in script.text
    assert 'headers.set("Authorization", `Bearer ${state.accessToken}`);' in script.text
    assert 'typeof crypto.randomUUID === "function"' in script.text
    assert "state.pendingMutations" in script.text
    assert "state.refreshPromise" in script.text
    assert "localStorage" not in script.text
    assert "sessionStorage" not in script.text


def test_product_access_panel_uses_existing_session_and_explicit_asset() -> None:
    """Static shell exposes no role grants; all account data comes from guarded APIs."""
    client = _client()
    page = client.get("/terminal/review")
    script = client.get("/terminal/product-access.js")
    assert script.status_code == 200
    assert script.headers["content-type"].startswith("application/javascript")
    assert script.headers["x-content-type-options"] == "nosniff"
    assert 'id="productAccessLink" href="#productAccess" hidden' in page.text
    assert 'id="accessDialog" aria-labelledby="accessDialogTitle"' in page.text
    assert 'id="accessReason"' in page.text
    assert 'maxlength="1000"' in page.text
    assert "localStorage" not in script.text
    assert "sessionStorage" not in script.text
    assert "innerHTML" not in script.text
    assert 'headers: { "Idempotency-Key": command.key }' in script.text
    assert "createProductAccess" in script.text
    assert "bootstrap" not in script.text


def test_review_uses_shared_presentation_and_explicit_pair_confirmation() -> None:
    """Protect the real cabinet's confirmation and locally scoped error feedback."""
    client = _client()
    page = client.get("/terminal/review").text
    script = client.get("/terminal/review.js").text
    styles = client.get("/terminal/review.css").text

    assert 'id="decisionDialog"' in page
    assert 'aria-labelledby="decisionDialogTitle"' in page
    assert 'id="decisionSource"' in page
    assert 'id="decisionTargetId"' in page
    assert 'value="cancel" autofocus' in page
    assert 'src="/terminal/review.js" type="module"' in page
    assert 'from "/terminal/preview/presentation.js"' in script
    assert "window.confirm" not in script
    assert "async function confirmDecision(card, action, reason)" in script
    assert "tenantId === state.activeTenantId" in script
    assert "sessionEpoch === state.sessionEpoch" in script
    assert "setCardMessage(card, errorMessage(error))" in script
    assert 'control.dataset.previouslyDisabled === "true"' in script
    assert "prefers-reduced-motion: reduce" in styles
    assert "text-overflow: ellipsis" not in styles
