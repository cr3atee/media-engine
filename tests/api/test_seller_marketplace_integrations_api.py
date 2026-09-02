from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config.settings import AdminApiSettings, AuthSettings
from app.domain.auth import PasswordCredential
from app.domain.marketplace_integrations import REDACTED_CREDENTIAL_REFERENCE
from app.domain.tenancy import Membership, Tenant, TenantRole, User
from app.main import create_app
from app.repositories.provider import RepositoryProvider, create_memory_provider
from app.repositories.queries.provider import ReadRepositoryProvider
from app.services.passwords import PasswordHasher
from app.services.repository_scope import create_memory_repository_scope
from tests.repositories.contracts.factories import run_async

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
TENANT_A_ID = UUID("23000000-0000-4000-8000-000000000101")
TENANT_B_ID = UUID("23000000-0000-4000-8000-000000000202")
ADMIN_USER_ID = UUID("13000000-0000-4000-8000-000000000101")
VIEWER_USER_ID = UUID("13000000-0000-4000-8000-000000000202")
PASSWORD = "correct horse battery staple"


def test_seller_can_create_read_and_scope_integrations() -> None:
    provider = create_memory_provider()
    run_async(_seed_identity(provider))
    client = _client(provider)
    admin_headers = _login_headers(client, "admin@example.com")

    created = client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/marketplace-integrations",
        headers=admin_headers,
        json={
            "marketplace": " GGSEL ",
            "display_name": " GGSEL main ",
            "enabled": True,
            "status": "active",
            "external_account_id": "seller-1",
            "source_url": "https://ggsel.net/catalog/minecraft",
        },
    )
    body = created.json()
    integration_id = body["id"]
    own_list = client.get(
        f"/api/v1/tenants/{TENANT_A_ID}/marketplace-integrations",
        headers=admin_headers,
    )
    foreign_detail = client.get(
        f"/api/v1/tenants/{TENANT_B_ID}/marketplace-integrations/{integration_id}",
        headers=admin_headers,
    )
    viewer_headers = _login_headers(client, "viewer@example.com")
    viewer_list = client.get(
        f"/api/v1/tenants/{TENANT_A_ID}/marketplace-integrations",
        headers=viewer_headers,
    )

    assert created.status_code == 201
    assert body["marketplace"] == "ggsel"
    assert body["display_name"] == "GGSEL main"
    assert body["credential"] == {
        "configured": False,
        "auth_type": "none",
        "reference": None,
        "configured_at": None,
        "last_rotated_at": None,
        "version": 0,
    }
    assert own_list.status_code == 200
    assert [item["id"] for item in own_list.json()] == [integration_id]
    assert foreign_detail.status_code == 404
    assert foreign_detail.json()["error"]["code"] == "resource_not_found"
    assert viewer_list.status_code == 200
    assert [item["id"] for item in viewer_list.json()] == [integration_id]


def test_viewer_cannot_manage_integrations() -> None:
    provider = create_memory_provider()
    run_async(_seed_identity(provider))
    client = _client(provider)
    headers = _login_headers(client, "viewer@example.com")

    response = client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/marketplace-integrations",
        headers=headers,
        json={
            "marketplace": "ggsel",
            "display_name": "GGSEL main",
            "source_url": "https://ggsel.net/catalog/minecraft",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


def test_seller_can_update_and_disable_integration() -> None:
    provider = create_memory_provider()
    run_async(_seed_identity(provider))
    client = _client(provider)
    headers = _login_headers(client, "admin@example.com")
    created = _create_integration(client, headers)
    integration_id = created["id"]

    updated = client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/marketplace-integrations/{integration_id}/update",
        headers=headers,
        json={
            "expected_version": created["version"],
            "display_name": "GGSEL updated",
            "external_account_id": None,
            "source_url": "https://ggsel.net/catalog/updated",
        },
    )
    stale = client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/marketplace-integrations/{integration_id}/update",
        headers=headers,
        json={
            "expected_version": created["version"],
            "display_name": "stale update",
        },
    )
    disabled = client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/marketplace-integrations/{integration_id}/disable",
        headers=headers,
        json={"expected_version": updated.json()["version"]},
    )

    assert updated.status_code == 200
    assert updated.json()["display_name"] == "GGSEL updated"
    assert updated.json()["external_account_id"] is None
    assert updated.json()["version"] == 2
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "optimistic_concurrency_conflict"
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert disabled.json()["status"] == "disabled"
    assert disabled.json()["version"] == 3


def test_seller_credential_rotation_is_redacted_and_version_guarded() -> None:
    provider = create_memory_provider()
    run_async(_seed_identity(provider))
    client = _client(provider)
    headers = _login_headers(client, "admin@example.com")
    created = _create_integration(client, headers)
    integration_id = UUID(created["id"])
    secret_reference = "secret://tenant-a/ggsel/main"

    rotated = client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/marketplace-integrations/{integration_id}/credentials/rotate",
        headers=headers,
        json={
            "expected_version": created["version"],
            "auth_type": "api_key",
            "credential_reference": secret_reference,
            "reason": "initial setup",
        },
    )
    stale = client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/marketplace-integrations/{integration_id}/credentials/rotate",
        headers=headers,
        json={
            "expected_version": created["version"],
            "auth_type": "api_key",
            "credential_reference": "secret://tenant-a/ggsel/stale",
        },
    )
    stored = run_async(
        provider.marketplace_integrations.get_by_tenant_and_id(
            TENANT_A_ID,
            integration_id,
        )
    )

    assert rotated.status_code == 200
    assert secret_reference not in rotated.text
    assert rotated.json()["credential"]["reference"] == REDACTED_CREDENTIAL_REFERENCE
    assert rotated.json()["credential"]["configured"] is True
    assert rotated.json()["credential"]["version"] == 1
    assert rotated.json()["auth_type"] == "api_key"
    assert rotated.json()["version"] == 2
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "optimistic_concurrency_conflict"
    assert stored is not None
    assert stored.credential is not None
    assert stored.credential.reference == secret_reference


def test_duplicate_identity_is_rejected_only_within_tenant() -> None:
    provider = create_memory_provider()
    run_async(_seed_identity(provider))
    client = _client(provider)
    headers = _login_headers(client, "admin@example.com")
    payload = {
        "marketplace": "ggsel",
        "display_name": "GGSEL main",
        "source_url": "https://ggsel.net/catalog/minecraft",
    }

    first = client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/marketplace-integrations",
        headers=headers,
        json=payload,
    )
    duplicate = client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/marketplace-integrations",
        headers=headers,
        json={**payload, "display_name": "GGSEL duplicate"},
    )
    tenant_b = client.post(
        f"/api/v1/tenants/{TENANT_B_ID}/marketplace-integrations",
        headers=headers,
        json={**payload, "display_name": "GGSEL tenant B"},
    )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "integration_identity_conflict"
    assert tenant_b.status_code == 201


def _create_integration(
    client: TestClient,
    headers: dict[str, str],
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/marketplace-integrations",
        headers=headers,
        json={
            "marketplace": "ggsel",
            "display_name": "GGSEL main",
            "enabled": True,
            "status": "active",
            "external_account_id": "seller-1",
            "source_url": "https://ggsel.net/catalog/minecraft",
        },
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def _client(provider: RepositoryProvider) -> TestClient:
    @asynccontextmanager
    async def read_scope() -> AsyncIterator[ReadRepositoryProvider]:
        from app.repositories.queries.provider import create_memory_read_provider

        yield create_memory_read_provider()

    application = create_app(
        admin_api_settings=AdminApiSettings(
            api_enabled=True,
            api_key=SecretStr("admin-secret"),
        ),
        auth_settings=AuthSettings(access_token_secret=SecretStr("auth-secret")),
        read_repository_scope_factory=read_scope,
        repository_scope_factory=create_memory_repository_scope(provider),
    )
    return TestClient(application, raise_server_exceptions=False)


def _login_headers(client: TestClient, email: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _seed_identity(provider: RepositoryProvider) -> None:
    hasher = PasswordHasher(iterations=100_000)
    for tenant_id, name in (
        (TENANT_A_ID, "Tenant A"),
        (TENANT_B_ID, "Tenant B"),
    ):
        await provider.tenants.create(
            Tenant(
                id=tenant_id,
                name=name,
                slug=name.lower().replace(" ", "-"),
                created_at=NOW,
                updated_at=NOW,
            )
        )
    for user_id, email in (
        (ADMIN_USER_ID, "admin@example.com"),
        (VIEWER_USER_ID, "viewer@example.com"),
    ):
        await provider.users.create(
            User(
                id=user_id,
                email=email,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await provider.password_credentials.set_for_user(
            PasswordCredential(
                user_id=user_id,
                password_hash=hasher.hash_password(PASSWORD),
                created_at=NOW,
                updated_at=NOW,
            )
        )
    for tenant_id in (TENANT_A_ID, TENANT_B_ID):
        await provider.memberships.create(
            Membership(
                id=uuid4(),
                user_id=ADMIN_USER_ID,
                tenant_id=tenant_id,
                role=TenantRole.ADMINISTRATOR,
                joined_at=NOW,
                updated_at=NOW,
            )
        )
    await provider.memberships.create(
        Membership(
            id=uuid4(),
            user_id=VIEWER_USER_ID,
            tenant_id=TENANT_A_ID,
            role=TenantRole.VIEWER,
            joined_at=NOW,
            updated_at=NOW,
        )
    )
