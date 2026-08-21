from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config.settings import AdminApiSettings, AuthSettings
from app.domain.auth import PasswordCredential
from app.domain.tenancy import Membership, Tenant, TenantRole, User
from app.main import create_app
from app.repositories.provider import RepositoryProvider, create_memory_provider
from app.repositories.queries.provider import ReadRepositoryProvider
from app.services.passwords import PasswordHasher
from app.services.repository_scope import create_memory_repository_scope
from tests.repositories.contracts.factories import run_async

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
USER_ID = UUID("11000000-0000-4000-8000-000000000001")
TENANT_ID = UUID("22000000-0000-4000-8000-000000000001")
MEMBERSHIP_ID = UUID("33000000-0000-4000-8000-000000000001")
PASSWORD = "correct horse battery staple"


def test_seller_login_me_tenant_context_and_logout() -> None:
    provider = create_memory_provider()
    run_async(_seed_identity(provider))
    client = _client(provider)

    missing_secret = _client(provider, secret="")
    unavailable = missing_secret.post(
        "/api/v1/auth/login",
        json={"email": "seller@example.com", "password": PASSWORD},
    )
    invalid = client.post(
        "/api/v1/auth/login",
        json={"email": "seller@example.com", "password": "wrong"},
    )
    malformed = client.post(
        "/api/v1/auth/login",
        json={"email": "not-an-email", "password": PASSWORD},
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "SELLER@example.com", "password": PASSWORD},
    )

    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "authentication_unavailable"
    assert invalid.status_code == 401
    assert invalid.json()["error"]["code"] == "invalid_credentials"
    assert malformed.status_code == 401
    assert malformed.json()["error"]["code"] == "invalid_credentials"
    assert PASSWORD not in invalid.text
    assert PASSWORD not in malformed.text
    assert login.status_code == 200

    tokens = login.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/me", headers=headers)
    context = client.get(f"/api/v1/tenants/{TENANT_ID}/context", headers=headers)

    assert me.status_code == 200
    assert me.json()["user"]["email"] == "seller@example.com"
    assert me.json()["memberships"][0]["tenant_id"] == str(TENANT_ID)
    assert context.status_code == 200
    assert context.json()["role"] == "reviewer"
    assert "content_review" in context.json()["permissions"]

    logout = client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
    )
    after_logout = client.get("/api/v1/me", headers=headers)

    assert logout.status_code == 200
    assert after_logout.status_code == 401
    assert after_logout.json()["error"]["code"] == "token_revoked"
    assert tokens["refresh_token"] not in logout.text


def test_password_reset_api_does_not_expose_reset_token() -> None:
    provider = create_memory_provider()
    run_async(_seed_identity(provider))
    client = _client(provider)

    response = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "seller@example.com"},
    )
    unknown = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "missing@example.com"},
    )
    malformed = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "not-an-email"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    assert "reset_token" not in response.text
    assert unknown.status_code == 200
    assert unknown.json() == {"status": "accepted"}
    assert malformed.status_code == 200
    assert malformed.json() == {"status": "accepted"}


def test_membership_removal_is_reflected_by_existing_access_token() -> None:
    provider = create_memory_provider()
    run_async(_seed_identity(provider))
    client = _client(provider)
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "seller@example.com", "password": PASSWORD},
    )
    tokens = login.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    run_async(_deactivate_membership(provider))
    response = client.get(f"/api/v1/tenants/{TENANT_ID}/context", headers=headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "tenant_not_found"


def _client(provider: RepositoryProvider, *, secret: str = "auth-secret") -> TestClient:
    @asynccontextmanager
    async def read_scope() -> AsyncIterator[ReadRepositoryProvider]:
        from app.repositories.queries.provider import create_memory_read_provider

        yield create_memory_read_provider()

    application = create_app(
        admin_api_settings=AdminApiSettings(
            api_enabled=True,
            api_key=SecretStr("admin-secret"),
        ),
        auth_settings=AuthSettings(access_token_secret=SecretStr(secret)),
        read_repository_scope_factory=read_scope,
        repository_scope_factory=create_memory_repository_scope(provider),
    )
    return TestClient(application, raise_server_exceptions=False)


async def _seed_identity(provider: RepositoryProvider) -> None:
    hasher = PasswordHasher(iterations=100_000)
    await provider.users.create(
        User(
            id=USER_ID,
            email="seller@example.com",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await provider.tenants.create(
        Tenant(
            id=TENANT_ID,
            name="Seller Workspace",
            slug="seller-workspace",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await provider.memberships.create(
        Membership(
            id=MEMBERSHIP_ID,
            user_id=USER_ID,
            tenant_id=TENANT_ID,
            role=TenantRole.REVIEWER,
            joined_at=NOW,
            updated_at=NOW,
        )
    )
    await provider.password_credentials.set_for_user(
        PasswordCredential(
            user_id=USER_ID,
            password_hash=hasher.hash_password(PASSWORD),
            created_at=NOW,
            updated_at=NOW,
        )
    )


async def _deactivate_membership(provider: RepositoryProvider) -> None:
    membership = await provider.memberships.get_by_user_and_tenant(USER_ID, TENANT_ID)
    assert membership is not None
    await provider.memberships.set_active(
        USER_ID,
        TENANT_ID,
        False,
        membership.version,
    )
