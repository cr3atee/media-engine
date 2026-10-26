"""Cookie transport preserves auth service revocation and rejects cross-site writes."""

from fastapi.testclient import TestClient

from app.repositories.provider import create_memory_provider
from tests.api.test_seller_auth_api import PASSWORD, _client, _seed_identity
from tests.repositories.contracts.factories import run_async

BASE = "/api/v1/auth/browser"
HEADERS = {"Origin": "https://testserver", "X-Terminal-Request": "1"}
LOGIN = {"email": "seller@example.com", "password": PASSWORD}


def client() -> TestClient:
    provider = create_memory_provider()
    run_async(_seed_identity(provider))
    return TestClient(_client(provider).app, base_url="https://testserver")


def test_browser_cookie_navigation_rotation_logout_and_api_compatibility() -> None:
    c = client()
    assert c.post(f"{BASE}/refresh", headers=HEADERS).status_code == 401
    login = c.post(f"{BASE}/login", headers=HEADERS, json=LOGIN)
    assert login.status_code == 200
    assert "refresh_token" not in login.json()
    cookie = login.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
    assert f"Path={BASE}" in cookie and "Domain=" not in cookie
    assert login.headers["cache-control"] == "no-store"
    old_cookie = c.cookies.get("__Secure-mt_refresh")
    assert old_cookie
    assert c.get("/terminal").status_code == 200
    assert c.get("/terminal/review").status_code == 200
    # Page navigation discards JS state, not the browser refresh cookie.
    restored = c.post(f"{BASE}/refresh", headers=HEADERS)
    assert restored.status_code == 200
    assert c.cookies.get("__Secure-mt_refresh") != old_cookie
    token = restored.json()["access_token"]
    assert (
        c.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"}).status_code
        == 200
    )
    assert c.get("/api/v1/me").status_code == 401  # cookie alone grants no data access
    assert c.post(f"{BASE}/logout", headers=HEADERS).status_code == 200
    assert c.cookies.get("__Secure-mt_refresh") is None
    assert (
        c.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"}).status_code
        == 401
    )
    assert c.post(f"{BASE}/refresh", headers=HEADERS).status_code == 401
    old = c.post("/api/v1/auth/login", json=LOGIN)
    assert old.status_code == 200 and "refresh_token" in old.json()


def test_cookie_requests_require_same_origin_and_non_simple_header() -> None:
    c = client()
    for headers in (
        {},
        {"Origin": "https://testserver"},
        {
            **HEADERS,
            "Origin": "https://attacker.test",
        },
        {**HEADERS, "Sec-Fetch-Site": "cross-site"},
    ):
        for path in ("login", "refresh", "logout"):
            result = c.post(
                f"{BASE}/{path}",
                headers=headers,
                json=LOGIN if path == "login" else None,
            )
            assert result.status_code == 403
            assert "set-cookie" not in result.headers
    c.post(f"{BASE}/login", headers=HEADERS, json=LOGIN)
    cookie = c.cookies.get("__Secure-mt_refresh")
    assert c.post(f"{BASE}/logout").status_code == 403
    assert c.cookies.get("__Secure-mt_refresh") == cookie
    assert c.post(f"{BASE}/refresh", headers=HEADERS).status_code == 200


def test_http_is_rejected_outside_loopback_and_bad_refresh_clears_cookie() -> None:
    c = client()
    insecure = TestClient(c.app, base_url="http://example.test")
    result = insecure.post(
        f"{BASE}/login",
        headers={
            "Origin": "http://example.test",
            "X-Terminal-Request": "1",
        },
        json=LOGIN,
    )
    assert result.status_code == 503 and "set-cookie" not in result.headers
    c.cookies.set("__Secure-mt_refresh", "invalid-opaque-token", path=BASE)
    failure = c.post(f"{BASE}/refresh", headers=HEADERS)
    assert failure.status_code == 401
    assert "Max-Age=0" in failure.headers["set-cookie"]
    assert "invalid-opaque-token" not in failure.text


def test_loopback_development_cookie() -> None:
    c = client()
    local = TestClient(c.app, base_url="http://127.0.0.1", client=("127.0.0.1", 12345))
    headers = {"Origin": "http://127.0.0.1", "X-Terminal-Request": "1"}
    result = local.post(f"{BASE}/login", headers=headers, json=LOGIN)
    assert result.status_code == 200
    assert "mt_refresh_local=" in result.headers["set-cookie"]
    assert "HttpOnly" in result.headers["set-cookie"]
    assert local.post(f"{BASE}/refresh", headers=headers).status_code == 200
