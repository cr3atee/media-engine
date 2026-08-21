"""Verify EPIC 16 Task 2 authentication and authorization against PostgreSQL."""

# ruff: noqa: E402, I001
from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_CONFIGURED_DATABASE_URL = os.getenv("EPIC16_DATABASE_URL", "").strip()
if _CONFIGURED_DATABASE_URL:
    os.environ["DATABASE_URL"] = _CONFIGURED_DATABASE_URL

from app.config.settings import AdminApiSettings, AuthSettings, settings
from app.database.repository_scope import create_postgres_repository_scope
from app.domain.auth import PasswordCredential
from app.domain.tenancy import Membership, Tenant, TenantRole, User
from app.main import create_app
from app.repositories.queries.provider import ReadRepositoryProvider
from app.repositories.queries.provider import create_memory_read_provider
from app.services.authentication import AuthenticationService
from app.services.auth_tokens import SignedAccessTokenService
from app.services.passwords import PasswordHasher

DATABASE_URL_ENV = "EPIC16_DATABASE_URL"
NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
USER_ID = UUID("12000000-0000-4000-8000-000000000001")
TENANT_ID = UUID("22000000-0000-4000-8000-000000000001")
MEMBERSHIP_ID = UUID("32000000-0000-4000-8000-000000000001")
PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "new correct horse battery staple"


class Verification:
    """Collect named verification checks."""

    def __init__(self) -> None:
        self.passed: list[str] = []

    def check(self, name: str, condition: bool) -> None:
        """Record one passing check or fail with a named assertion."""
        if not condition:
            raise AssertionError(name)
        self.passed.append(name)
        print(f"PASS: {name}")


async def main() -> int:
    """Run Task 2 verification against an isolated PostgreSQL database."""
    database_url = _CONFIGURED_DATABASE_URL
    if not database_url:
        print(f"SKIPPED: set {DATABASE_URL_ENV} to an isolated PostgreSQL URL.")
        return 0
    _require_isolated_database(database_url)
    os.environ["DATABASE_URL"] = database_url

    verifier = Verification()
    await _recreate_schema(database_url)
    await asyncio.to_thread(_apply_migrations, database_url, "head")
    await _seed_identity(database_url)

    with _client(database_url) as client:
        _verify_http_flow(client, verifier)
        await _verify_direct_reset_flow(database_url, client, verifier)
    await _verify_fresh_session_persistence(database_url, verifier)

    print(f"EPIC 16 auth verification: {len(verifier.passed)} checks passed.")
    return 0


def _verify_http_flow(client: TestClient, verifier: Verification) -> None:
    invalid = client.post(
        "/api/v1/auth/login",
        json={"email": "seller@example.com", "password": "wrong"},
    )
    verifier.check(
        "invalid login uses stable error",
        invalid.status_code == 401
        and invalid.json()["error"]["code"] == "invalid_credentials"
        and PASSWORD not in invalid.text,
    )

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "SELLER@example.com", "password": PASSWORD},
    )
    verifier.check("login succeeds", login.status_code == 200)
    tokens = login.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    me = client.get("/api/v1/me", headers=headers)
    verifier.check(
        "me returns current user and membership",
        me.status_code == 200
        and me.json()["user"]["email"] == "seller@example.com"
        and me.json()["memberships"][0]["tenant_id"] == str(TENANT_ID),
    )

    context = client.get(f"/api/v1/tenants/{TENANT_ID}/context", headers=headers)
    verifier.check(
        "tenant context resolves role and permissions",
        context.status_code == 200
        and context.json()["role"] == "viewer"
        and "dashboard_read" in context.json()["permissions"],
    )

    refresh = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    verifier.check(
        "refresh rotates token",
        refresh.status_code == 200
        and refresh.json()["refresh_token"] != tokens["refresh_token"],
    )
    old_refresh = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    verifier.check(
        "old refresh token is rejected",
        old_refresh.status_code == 401
        and old_refresh.json()["error"]["code"] == "token_revoked",
    )

    logout = client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": refresh.json()["refresh_token"]},
    )
    after_logout = client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {refresh.json()['access_token']}"},
    )
    verifier.check(
        "logout revokes access session",
        logout.status_code == 200
        and after_logout.status_code == 401
        and after_logout.json()["error"]["code"] == "token_revoked",
    )
    verifier.check(
        "tokens are not echoed in logout response",
        refresh.json()["refresh_token"] not in logout.text,
    )

    reset_request = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "seller@example.com"},
    )
    unknown_reset = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "missing@example.com"},
    )
    verifier.check(
        "password reset request is enumeration-safe",
        reset_request.status_code == 200
        and unknown_reset.status_code == 200
        and reset_request.json() == {"status": "accepted"}
        and "reset_token" not in reset_request.text,
    )


async def _verify_direct_reset_flow(
    database_url: str,
    client: TestClient,
    verifier: Verification,
) -> None:
    service = _auth_service(database_url)
    tokens = await service.login(email="seller@example.com", password=PASSWORD)
    reset = await service.request_password_reset(email="seller@example.com")
    verifier.check(
        "reset token is stored but not public", reset.reset_token is not None
    )
    await service.complete_password_reset(
        reset_token=reset.reset_token or "",
        new_password=NEW_PASSWORD,
    )
    revoked = client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {tokens.access_token}"},
    )
    verifier.check(
        "password reset revokes existing sessions",
        revoked.status_code == 401
        and revoked.json()["error"]["code"] == "token_revoked",
    )
    old_password = client.post(
        "/api/v1/auth/login",
        json={"email": "seller@example.com", "password": PASSWORD},
    )
    new_password = client.post(
        "/api/v1/auth/login",
        json={"email": "seller@example.com", "password": NEW_PASSWORD},
    )
    verifier.check(
        "password reset rotates credentials",
        old_password.status_code == 401 and new_password.status_code == 200,
    )


async def _verify_fresh_session_persistence(
    database_url: str,
    verifier: Verification,
) -> None:
    engine = create_async_engine(database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            async with session.begin():
                from app.repositories.provider import create_postgres_provider

                repositories = create_postgres_provider(session)
                membership = await repositories.memberships.get_by_user_and_tenant(
                    USER_ID,
                    TENANT_ID,
                )
                assert membership is not None
                await repositories.memberships.update_role(
                    USER_ID,
                    TENANT_ID,
                    TenantRole.REVIEWER,
                    membership.version,
                )

        with _client(database_url) as client:
            login = client.post(
                "/api/v1/auth/login",
                json={"email": "seller@example.com", "password": NEW_PASSWORD},
            )
            access_token = login.json()["access_token"]
            context = client.get(
                f"/api/v1/tenants/{TENANT_ID}/context",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            verifier.check(
                "role changes apply to existing tenant context lookups",
                context.status_code == 200 and context.json()["role"] == "reviewer",
            )

            async with session_factory() as session:
                async with session.begin():
                    from app.repositories.provider import create_postgres_provider

                    repositories = create_postgres_provider(session)
                    membership = await repositories.memberships.get_by_user_and_tenant(
                        USER_ID,
                        TENANT_ID,
                    )
                    assert membership is not None
                    await repositories.memberships.set_active(
                        USER_ID,
                        TENANT_ID,
                        False,
                        membership.version,
                    )
            hidden = client.get(
                f"/api/v1/tenants/{TENANT_ID}/context",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            verifier.check(
                "membership removal hides tenant context",
                hidden.status_code == 404
                and hidden.json()["error"]["code"] == "tenant_not_found",
            )
    finally:
        await engine.dispose()


async def _seed_identity(database_url: str) -> None:
    engine = create_async_engine(database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    hasher = PasswordHasher(iterations=100_000)
    try:
        async with session_factory() as session:
            async with session.begin():
                from app.repositories.provider import create_postgres_provider

                repositories = create_postgres_provider(session)
                await repositories.users.create(
                    User(
                        id=USER_ID,
                        email="seller@example.com",
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
                await repositories.tenants.create(
                    Tenant(
                        id=TENANT_ID,
                        name="Seller Workspace",
                        slug="seller-workspace",
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
                await repositories.memberships.create(
                    Membership(
                        id=MEMBERSHIP_ID,
                        user_id=USER_ID,
                        tenant_id=TENANT_ID,
                        role=TenantRole.VIEWER,
                        joined_at=NOW,
                        updated_at=NOW,
                    )
                )
                await repositories.password_credentials.set_for_user(
                    PasswordCredential(
                        user_id=USER_ID,
                        password_hash=hasher.hash_password(PASSWORD),
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
    finally:
        await engine.dispose()


def _client(database_url: str) -> TestClient:
    @asynccontextmanager
    async def read_scope() -> AsyncIterator[ReadRepositoryProvider]:
        yield create_memory_read_provider()

    engine = create_async_engine(database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app(
        admin_api_settings=AdminApiSettings(
            api_enabled=True,
            api_key=SecretStr("admin-secret"),
        ),
        auth_settings=_auth_settings(),
        read_repository_scope_factory=read_scope,
        repository_scope_factory=create_postgres_repository_scope(session_factory),
    )
    return TestClient(app, raise_server_exceptions=False)


def _auth_service(database_url: str) -> AuthenticationService:
    engine = create_async_engine(database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    auth_settings = _auth_settings()
    token_service = SignedAccessTokenService(
        secret=auth_settings.access_token_secret.get_secret_value(),
        ttl_seconds=auth_settings.access_token_ttl_seconds,
        issuer=auth_settings.token_issuer,
        audience=auth_settings.token_audience,
    )
    return AuthenticationService(
        create_postgres_repository_scope(session_factory),
        token_service,
        PasswordHasher(iterations=100_000),
        access_token_ttl_seconds=auth_settings.access_token_ttl_seconds,
        refresh_token_ttl_seconds=auth_settings.refresh_token_ttl_seconds,
        password_reset_token_ttl_seconds=(
            auth_settings.password_reset_token_ttl_seconds
        ),
    )


async def _recreate_schema(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


def _apply_migrations(database_url: str, revision: str) -> None:
    os.environ["DATABASE_URL"] = database_url
    settings.database.url = database_url
    command.upgrade(Config(str(ROOT / "alembic.ini")), revision)


def _auth_settings() -> AuthSettings:
    return AuthSettings(
        access_token_secret=SecretStr("epic16-auth-secret"),
        password_hash_iterations=100_000,
    )


def _require_isolated_database(database_url: str) -> None:
    database_name = make_url(database_url).database or ""
    if not database_name.startswith("epic16_"):
        msg = (
            f"{DATABASE_URL_ENV} must target an isolated epic16_* database; "
            f"got {database_name!r}."
        )
        raise RuntimeError(msg)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
