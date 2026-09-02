"""Verify EPIC 17 seller marketplace integration API against PostgreSQL."""

# ruff: noqa: E402, I001
from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_CONFIGURED_DATABASE_URL = os.getenv("EPIC17_DATABASE_URL", "").strip()
if _CONFIGURED_DATABASE_URL:
    os.environ["DATABASE_URL"] = _CONFIGURED_DATABASE_URL

from app.config.settings import AdminApiSettings, AuthSettings
from app.domain.auth import PasswordCredential
from app.domain.marketplace_integrations import REDACTED_CREDENTIAL_REFERENCE
from app.domain.tenancy import Membership, Tenant, TenantRole, User
from app.main import create_app
from app.repositories.queries.provider import (
    ReadRepositoryProvider,
    create_memory_read_provider,
)
from app.repositories.provider import RepositoryProvider, create_postgres_provider
from app.services.passwords import PasswordHasher
from app.services.repository_scope import RepositoryScopeFactory

DATABASE_URL_ENV = "EPIC17_DATABASE_URL"
TENANT_A_ID = UUID("24000000-0000-4000-8000-000000000101")
TENANT_B_ID = UUID("24000000-0000-4000-8000-000000000202")
ADMIN_USER_ID = UUID("14000000-0000-4000-8000-000000000101")
VIEWER_USER_ID = UUID("14000000-0000-4000-8000-000000000202")
NOW = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)
PASSWORD = "correct horse battery staple"


class Verification:
    """Collect and print named verification checks."""

    def __init__(self) -> None:
        self.passed: list[str] = []

    def check(self, name: str, condition: bool) -> None:
        """Record one passing check or raise a diagnostic assertion."""
        if not condition:
            raise AssertionError(name)
        self.passed.append(name)
        print(f"PASS: {name}")


async def main() -> int:
    """Run seller integration API verification on an isolated database."""
    database_url = _CONFIGURED_DATABASE_URL
    if not database_url:
        print(f"SKIPPED: set {DATABASE_URL_ENV} to an isolated PostgreSQL URL.")
        return 0
    _require_isolated_database(database_url)
    os.environ["DATABASE_URL"] = database_url

    verifier = Verification()
    await _recreate_schema(database_url)
    await asyncio.to_thread(_apply_migrations, database_url, "head")

    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    repository_scope_factory = _repository_scope_factory(session_factory)
    try:
        async with repository_scope_factory() as repositories:
            await _seed_identity(repositories)

        application = _application(repository_scope_factory)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://epic17-seller-integrations.test",
        ) as client:
            admin_headers = await _login_headers(client, "admin@example.com")
            viewer_headers = await _login_headers(client, "viewer@example.com")

            await _verify_authentication_and_permissions(
                client,
                admin_headers,
                viewer_headers,
                verifier,
            )
            created = await _verify_create_list_and_scope(
                client,
                admin_headers,
                verifier,
            )
            updated = await _verify_update_and_conflicts(
                client,
                admin_headers,
                created,
                verifier,
            )
            rotated = await _verify_credential_rotation(
                client,
                admin_headers,
                updated,
                verifier,
            )
            await _verify_disable(client, admin_headers, rotated, verifier)
        await _verify_fresh_session_persistence(
            repository_scope_factory,
            UUID(rotated["id"]),
            verifier,
        )
    finally:
        await engine.dispose()

    print(
        "EPIC 17 seller marketplace integration API PostgreSQL verification: "
        f"{len(verifier.passed)} checks passed."
    )
    return 0


async def _verify_authentication_and_permissions(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    viewer_headers: dict[str, str],
    verifier: Verification,
) -> None:
    missing_auth = await client.get(
        f"/api/v1/tenants/{TENANT_A_ID}/marketplace-integrations",
    )
    viewer_create = await client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/marketplace-integrations",
        headers=viewer_headers,
        json={
            "marketplace": "ggsel",
            "display_name": "GGSEL viewer",
            "source_url": "https://ggsel.net/catalog/viewer",
        },
    )
    admin_list = await client.get(
        f"/api/v1/tenants/{TENANT_A_ID}/marketplace-integrations",
        headers=admin_headers,
    )

    verifier.check(
        "missing seller bearer token is rejected",
        missing_auth.status_code == 401
        and missing_auth.json()["error"]["code"] == "authentication_required",
    )
    verifier.check(
        "viewer cannot manage integrations",
        viewer_create.status_code == 403
        and viewer_create.json()["error"]["code"] == "permission_denied",
    )
    verifier.check(
        "admin can read empty integration list",
        admin_list.status_code == 200 and admin_list.json() == [],
    )


async def _verify_create_list_and_scope(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    verifier: Verification,
) -> dict[str, Any]:
    created = await client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/marketplace-integrations",
        headers=headers,
        json={
            "marketplace": " GGSEL ",
            "display_name": " GGSEL main ",
            "enabled": True,
            "status": "active",
            "external_account_id": "seller-1",
            "source_url": "https://ggsel.net/catalog/minecraft",
        },
    )
    body = cast(dict[str, Any], created.json())
    own_list = await client.get(
        f"/api/v1/tenants/{TENANT_A_ID}/marketplace-integrations",
        headers=headers,
    )
    foreign_detail = await client.get(
        f"/api/v1/tenants/{TENANT_B_ID}/marketplace-integrations/{body['id']}",
        headers=headers,
    )
    duplicate = await client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/marketplace-integrations",
        headers=headers,
        json={
            "marketplace": "ggsel",
            "display_name": "GGSEL duplicate",
            "source_url": "https://ggsel.net/catalog/minecraft",
        },
    )
    tenant_b = await client.post(
        f"/api/v1/tenants/{TENANT_B_ID}/marketplace-integrations",
        headers=headers,
        json={
            "marketplace": "ggsel",
            "display_name": "GGSEL tenant B",
            "source_url": "https://ggsel.net/catalog/minecraft",
        },
    )

    verifier.check(
        "integration create succeeds",
        created.status_code == 201
        and body["marketplace"] == "ggsel"
        and body["credential"]["configured"] is False,
    )
    verifier.check(
        "integration list is tenant scoped",
        own_list.status_code == 200
        and [item["id"] for item in own_list.json()] == [body["id"]],
    )
    verifier.check(
        "cross-tenant integration detail is hidden",
        foreign_detail.status_code == 404
        and foreign_detail.json()["error"]["code"] == "resource_not_found",
    )
    verifier.check(
        "duplicate integration identity rolls back cleanly",
        duplicate.status_code == 409
        and duplicate.json()["error"]["code"] == "integration_identity_conflict",
    )
    verifier.check(
        "same integration identity is allowed in another tenant",
        tenant_b.status_code == 201,
    )
    return body


async def _verify_update_and_conflicts(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    created: dict[str, Any],
    verifier: Verification,
) -> dict[str, Any]:
    integration_id = created["id"]
    updated = await client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/marketplace-integrations/{integration_id}/update",
        headers=headers,
        json={
            "expected_version": created["version"],
            "display_name": "GGSEL updated",
            "external_account_id": None,
            "source_url": "https://ggsel.net/catalog/updated",
        },
    )
    body = cast(dict[str, Any], updated.json())
    stale = await client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/marketplace-integrations/{integration_id}/update",
        headers=headers,
        json={"expected_version": created["version"], "display_name": "stale"},
    )

    verifier.check(
        "integration update succeeds",
        updated.status_code == 200
        and body["display_name"] == "GGSEL updated"
        and body["external_account_id"] is None
        and body["version"] == 2,
    )
    verifier.check(
        "stale integration update is rejected",
        stale.status_code == 409
        and stale.json()["error"]["code"] == "optimistic_concurrency_conflict",
    )
    return body


async def _verify_credential_rotation(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    updated: dict[str, Any],
    verifier: Verification,
) -> dict[str, Any]:
    integration_id = updated["id"]
    secret_reference = "secret://tenant-a/ggsel/main"
    rotated = await client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/marketplace-integrations/{integration_id}/credentials/rotate",
        headers=headers,
        json={
            "expected_version": updated["version"],
            "auth_type": "api_key",
            "credential_reference": secret_reference,
            "reason": "initial setup",
        },
    )
    body = cast(dict[str, Any], rotated.json())
    stale = await client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/marketplace-integrations/{integration_id}/credentials/rotate",
        headers=headers,
        json={
            "expected_version": updated["version"],
            "auth_type": "api_key",
            "credential_reference": "secret://tenant-a/ggsel/stale",
        },
    )
    invalid = await client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/marketplace-integrations/{integration_id}/credentials/rotate",
        headers=headers,
        json={
            "expected_version": body["version"],
            "auth_type": "none",
            "credential_reference": "secret://tenant-a/ggsel/invalid",
        },
    )

    verifier.check(
        "credential rotation returns redacted metadata",
        rotated.status_code == 200
        and secret_reference not in rotated.text
        and body["credential"]["configured"] is True
        and body["credential"]["reference"] == REDACTED_CREDENTIAL_REFERENCE
        and body["version"] == 3,
    )
    verifier.check(
        "stale credential rotation is rejected",
        stale.status_code == 409
        and stale.json()["error"]["code"] == "optimistic_concurrency_conflict",
    )
    verifier.check(
        "invalid credential rotation payload is sanitized",
        invalid.status_code == 422
        and "secret://tenant-a/ggsel/invalid" not in invalid.text,
    )
    return body


async def _verify_disable(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    rotated: dict[str, Any],
    verifier: Verification,
) -> None:
    disabled = await client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/marketplace-integrations/{rotated['id']}/disable",
        headers=headers,
        json={"expected_version": rotated["version"]},
    )
    body = disabled.json()

    verifier.check(
        "integration disable succeeds",
        disabled.status_code == 200
        and body["enabled"] is False
        and body["status"] == "disabled"
        and body["version"] == 4,
    )


async def _verify_fresh_session_persistence(
    repository_scope_factory: RepositoryScopeFactory,
    integration_id: UUID,
    verifier: Verification,
) -> None:
    async with repository_scope_factory() as repositories:
        integration = await repositories.marketplace_integrations.get_by_tenant_and_id(
            TENANT_A_ID,
            integration_id,
        )
        tenant_rows = await repositories.marketplace_integrations.list_by_tenant(
            TENANT_A_ID
        )

    verifier.check(
        "fresh-session credential metadata persists internally",
        integration is not None
        and integration.credential is not None
        and integration.credential.reference == "secret://tenant-a/ggsel/main"
        and integration.credential.version == 1,
    )
    verifier.check(
        "duplicate create did not leave partial row",
        len(tenant_rows) == 1,
    )


async def _seed_identity(repositories: RepositoryProvider) -> None:
    hasher = PasswordHasher(iterations=100_000)
    for tenant_id, name in (
        (TENANT_A_ID, "Tenant A"),
        (TENANT_B_ID, "Tenant B"),
    ):
        await repositories.tenants.create(
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
        await repositories.users.create(
            User(
                id=user_id,
                email=email,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await repositories.password_credentials.set_for_user(
            PasswordCredential(
                user_id=user_id,
                password_hash=hasher.hash_password(PASSWORD),
                created_at=NOW,
                updated_at=NOW,
            )
        )
    for tenant_id in (TENANT_A_ID, TENANT_B_ID):
        await repositories.memberships.create(
            Membership(
                id=uuid4(),
                user_id=ADMIN_USER_ID,
                tenant_id=tenant_id,
                role=TenantRole.ADMINISTRATOR,
                joined_at=NOW,
                updated_at=NOW,
            )
        )
    await repositories.memberships.create(
        Membership(
            id=uuid4(),
            user_id=VIEWER_USER_ID,
            tenant_id=TENANT_A_ID,
            role=TenantRole.VIEWER,
            joined_at=NOW,
            updated_at=NOW,
        )
    )


def _application(repository_scope_factory: RepositoryScopeFactory) -> FastAPI:
    @asynccontextmanager
    async def read_scope() -> AsyncIterator[ReadRepositoryProvider]:
        yield create_memory_read_provider()

    return create_app(
        admin_api_settings=AdminApiSettings(
            api_enabled=True,
            api_key=SecretStr("admin-secret"),
        ),
        auth_settings=AuthSettings(access_token_secret=SecretStr("auth-secret")),
        read_repository_scope_factory=read_scope,
        repository_scope_factory=repository_scope_factory,
    )


async def _login_headers(client: httpx.AsyncClient, email: str) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    if response.status_code != 200:
        raise AssertionError(response.text)
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _repository_scope_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> RepositoryScopeFactory:
    @asynccontextmanager
    async def repository_scope() -> AsyncIterator[RepositoryProvider]:
        async with session_factory() as session:
            async with session.begin():
                yield create_postgres_provider(session)

    return repository_scope


async def _recreate_schema(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


def _apply_migrations(database_url: str, revision: str) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, revision)


def _require_isolated_database(database_url: str) -> None:
    database_name = make_url(database_url).database or ""
    if not database_name.startswith("epic17_"):
        msg = (
            f"{DATABASE_URL_ENV} must point to an isolated epic17_* database; "
            f"got {database_name!r}."
        )
        raise RuntimeError(msg)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
