"""Product roles require live explicit grants, not forged headers or membership."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.domain.product_access import ProductRole
from app.domain.tenancy import TenantRole, User
from app.repositories.provider import create_memory_provider
from app.services.product_roles import ProductRoleService
from app.services.repository_scope import create_memory_repository_scope
from tests.api.test_seller_auth_api import (
    PASSWORD,
    TENANT_ID,
    USER_ID,
    _client,
    _seed_identity,
)
from tests.repositories.contracts.factories import run_async
from tests.services.test_product_roles import principal


@pytest.mark.parametrize("role", tuple(TenantRole))
def test_workspace_roles_never_grant_product_admin(role: TenantRole) -> None:
    provider = create_memory_provider()
    run_async(_seed_identity(provider))
    run_async(provider.memberships.update_role(USER_ID, TENANT_ID, role, 1))
    client = _client(provider)
    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "seller@example.com",
            "password": PASSWORD,
        },
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (
        client.get("/api/v1/me", headers=headers).json()["user"]["product_role"]
        == "user"
    )
    response = client.get(f"/api/v1/platform/users/{USER_ID}/role", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "product_admin_required"


def test_role_api_authorization_replay_conflicts_and_revocation() -> None:
    provider = create_memory_provider()
    run_async(_seed_identity(provider))
    target = uuid4()
    now = datetime.now(UTC)
    run_async(
        provider.users.create(
            User(id=target, email="target@example.test", created_at=now, updated_at=now)
        )
    )
    service = ProductRoleService(create_memory_repository_scope(provider))
    client = _client(provider)
    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "seller@example.com",
            "password": PASSWORD,
        },
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    path = f"/api/v1/platform/users/{target}/role"
    command = {"role": "partner", "expected_version": 1, "reason": "Onboarding"}
    assert client.get(path).status_code == 401
    assert (
        client.get(path, headers={"X-Admin-API-Key": "admin-secret"}).status_code == 401
    )
    assert (
        client.get("/api/v1/me", headers=headers).json()["user"]["product_role"]
        == "user"
    )
    denied = client.post(
        path,
        headers={
            **headers,
            "X-Role": "admin",
            "Idempotency-Key": "partner",
        },
        json=command,
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "product_admin_required"
    run_async(
        service.bootstrap(
            user_id=USER_ID,
            expected_version=1,
            reason="Operator",
            idempotency_key="boot",
        )
    )
    # The original token observes current privileges; it contains no trusted role grant.
    assert client.get(path, headers=headers).json()["product_role"] == "user"
    assert (
        client.get(f"/api/v1/tenants/{uuid4()}/context", headers=headers).status_code
        == 404
    )
    result = client.post(
        path, headers={**headers, "Idempotency-Key": "partner"}, json=command
    )
    assert result.status_code == 200, result.text
    replay = client.post(
        path, headers={**headers, "Idempotency-Key": "partner"}, json=command
    )
    assert replay.json() == result.json()
    assert "fingerprint" not in result.json() and "idempotency_key" not in result.json()
    assert client.get(path + "-audit", headers=headers).json() == [result.json()]
    assert (
        client.post(
            path,
            headers={**headers, "Idempotency-Key": "partner"},
            json={
                **command,
                "role": "moderator",
            },
        ).status_code
        == 409
    )
    assert (
        client.post(
            path,
            headers={**headers, "Idempotency-Key": "stale"},
            json={
                **command,
                "role": "moderator",
            },
        ).json()["error"]["code"]
        == "version_conflict"
    )
    assert (
        client.post(
            path,
            headers={**headers, "Idempotency-Key": "blank"},
            json={
                **command,
                "reason": "   ",
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/v1/platform/users/{USER_ID}/role",
            headers={
                **headers,
                "Idempotency-Key": "demote",
            },
            json={"role": "user", "expected_version": 2, "reason": "Retire"},
        ).json()["error"]["code"]
        == "last_product_admin"
    )
    run_async(
        service.assign(
            principal(USER_ID),
            user_id=target,
            role=ProductRole.ADMIN,
            expected_version=2,
            reason="Second admin",
            idempotency_key="second",
        )
    )
    run_async(
        service.assign(
            principal(target),
            user_id=USER_ID,
            role=ProductRole.USER,
            expected_version=2,
            reason="Retire",
            idempotency_key="retire",
        )
    )
    assert client.get(path, headers=headers).status_code == 403
    assert client.get(path + "-audit", headers=headers).status_code == 403
    assert (
        client.post(
            path, headers={**headers, "Idempotency-Key": "partner"}, json=command
        ).status_code
        == 403
    )
    assert PASSWORD not in result.text
