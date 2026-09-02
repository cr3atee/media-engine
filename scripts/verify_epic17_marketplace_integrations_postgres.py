"""Verify EPIC 17 marketplace integration foundation against PostgreSQL."""

# ruff: noqa: E402, I001
from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_CONFIGURED_DATABASE_URL = os.getenv("EPIC17_DATABASE_URL", "").strip()
if _CONFIGURED_DATABASE_URL:
    os.environ["DATABASE_URL"] = _CONFIGURED_DATABASE_URL

from app.domain.marketplace_integrations import (
    CredentialRotationIntent,
    MarketplaceAuthType,
    MarketplaceCredentialMetadata,
    MarketplaceIntegration,
    MarketplaceIntegrationStatus,
    REDACTED_CREDENTIAL_REFERENCE,
)
from app.domain.tenancy import Tenant
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.provider import create_postgres_provider

DATABASE_URL_ENV = "EPIC17_DATABASE_URL"
TENANT_A_ID = UUID("10000000-0000-4000-8000-000000000001")
TENANT_B_ID = UUID("10000000-0000-4000-8000-000000000002")
NOW = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)


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
    """Run EPIC 17 integration verification on an isolated database."""
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
    try:
        async with engine.begin() as connection:
            await _verify_schema(connection, verifier)

        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with session.begin():
                await _seed_tenants(session)

        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with session.begin():
                await _verify_repository_behavior(session, verifier)

        async with AsyncSession(engine, expire_on_commit=False) as session:
            await _verify_fresh_session_persistence(session, verifier)

        async with AsyncSession(engine, expire_on_commit=False) as session:
            await _verify_rollback(session, verifier)
    finally:
        await engine.dispose()

    print(
        "EPIC 17 marketplace integration PostgreSQL verification: "
        f"{len(verifier.passed)} checks passed."
    )
    return 0


async def _verify_schema(
    connection: AsyncConnection,
    verifier: Verification,
) -> None:
    table_exists = await connection.scalar(
        text("SELECT to_regclass('marketplace_integrations') IS NOT NULL"),
    )
    verifier.check("marketplace_integrations table exists", table_exists is True)

    expected = {
        "pk_marketplace_integrations",
        "fk_marketplace_integrations_tenant",
        "ck_marketplace_integrations_status",
        "ck_marketplace_integrations_auth_type",
        "ck_marketplace_integrations_credential_reference_nonempty",
        "ck_marketplace_integrations_credential_version",
        "ck_marketplace_integrations_auth_none_without_reference",
        "ck_marketplace_integrations_credential_state",
        "ck_marketplace_integrations_credential_rotation_time",
        "ck_marketplace_integrations_version",
        "uq_marketplace_integrations_tenant_marketplace_external_account",
        "uq_marketplace_integrations_tenant_marketplace_source_url",
        "ix_marketplace_integrations_tenant",
        "ix_marketplace_integrations_enabled_runs",
        "ix_marketplace_integrations_credentials",
    }
    rows = await connection.execute(
        text(
            """
            SELECT conname
            FROM pg_constraint
            WHERE conname = ANY(:names)
            UNION
            SELECT indexname
            FROM pg_indexes
            WHERE indexname = ANY(:names)
            """,
        ),
        {"names": list(expected)},
    )
    found = {row[0] for row in rows}
    verifier.check("integration constraints and indexes exist", expected <= found)

    columns = await connection.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'marketplace_integrations'
            AND column_name = ANY(:names)
            """,
        ),
        {
            "names": [
                "credential_reference",
                "credential_configured_at",
                "credential_last_rotated_at",
                "credential_version",
            ],
        },
    )
    verifier.check(
        "credential metadata columns exist",
        {row[0] for row in columns}
        == {
            "credential_reference",
            "credential_configured_at",
            "credential_last_rotated_at",
            "credential_version",
        },
    )


async def _seed_tenants(session: AsyncSession) -> None:
    repositories = create_postgres_provider(session)
    await repositories.tenants.create(
        Tenant(
            id=TENANT_A_ID,
            name="Tenant A",
            slug="tenant-a",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await repositories.tenants.create(
        Tenant(
            id=TENANT_B_ID,
            name="Tenant B",
            slug="tenant-b",
            created_at=NOW,
            updated_at=NOW,
        )
    )


async def _verify_repository_behavior(
    session: AsyncSession,
    verifier: Verification,
) -> None:
    repository = create_postgres_provider(session).marketplace_integrations
    tenant_a = _integration(
        number=1,
        tenant_id=TENANT_A_ID,
        external_account_id="seller-1",
        source_url="https://ggsel.net/catalog/minecraft",
    )
    tenant_b = _integration(
        number=2,
        tenant_id=TENANT_B_ID,
        external_account_id="seller-1",
        source_url="https://ggsel.net/catalog/minecraft",
    )
    disabled = _integration(
        number=3,
        tenant_id=TENANT_A_ID,
        enabled=False,
        external_account_id="disabled-seller",
        source_url="https://ggsel.net/catalog/disabled",
    )

    await repository.save(tenant_a)
    await repository.save(tenant_b)
    await repository.save(disabled)

    verifier.check(
        "same external account can exist in two tenants",
        await repository.get_by_tenant_and_id(TENANT_A_ID, tenant_a.id) == tenant_a
        and await repository.get_by_tenant_and_id(TENANT_B_ID, tenant_b.id) == tenant_b,
    )
    verifier.check(
        "cross-tenant integration detail is hidden",
        await repository.get_by_tenant_and_id(TENANT_B_ID, tenant_a.id) is None,
    )
    verifier.check(
        "tenant integration list is isolated",
        tuple(await repository.list_by_tenant(TENANT_A_ID)) == (tenant_a, disabled),
    )
    verifier.check(
        "enabled integration list excludes disabled rows",
        tuple(await repository.list_enabled()) == (tenant_a, tenant_b),
    )
    verifier.check(
        "enabled tenant integration list is isolated",
        tuple(await repository.list_enabled_by_tenant(TENANT_A_ID)) == (tenant_a,),
    )

    await repository.save(
        _integration(
            number=1,
            tenant_id=TENANT_A_ID,
            display_name="GGSEL updated",
            external_account_id="seller-1",
            source_url="https://ggsel.net/catalog/minecraft",
            version=2,
        )
    )
    updated = await repository.get_by_tenant_and_id(TENANT_A_ID, tenant_a.id)
    verifier.check(
        "integration update preserves tenant identity",
        updated is not None
        and updated.display_name == "GGSEL updated"
        and updated.version == 2,
    )
    assert updated is not None

    credential_result = await repository.update_credential_reference(
        CredentialRotationIntent(
            tenant_id=TENANT_A_ID,
            integration_id=updated.id,
            auth_type=MarketplaceAuthType.API_KEY,
            credential=_credential(number=20),
            actor_id="admin-1",
            requested_at=NOW + timedelta(minutes=21),
            expected_version=updated.version,
            reason="initial credential reference",
        )
    )
    verifier.check(
        "credential update returns only redacted metadata",
        credential_result is not None
        and credential_result.credential.configured is True
        and credential_result.credential.reference == REDACTED_CREDENTIAL_REFERENCE
        and credential_result.version == 3,
    )
    persisted_with_credential = await repository.get_by_tenant_and_id(
        TENANT_A_ID,
        updated.id,
    )
    verifier.check(
        "credential reference persists as internal metadata",
        persisted_with_credential is not None
        and persisted_with_credential.credential is not None
        and persisted_with_credential.credential.version == 1
        and persisted_with_credential.auth_type is MarketplaceAuthType.API_KEY,
    )
    verifier.check(
        "stale credential update is rejected",
        await repository.update_credential_reference(
            CredentialRotationIntent(
                tenant_id=TENANT_A_ID,
                integration_id=updated.id,
                auth_type=MarketplaceAuthType.API_KEY,
                credential=_credential(number=22),
                actor_id="admin-1",
                requested_at=NOW + timedelta(minutes=23),
                expected_version=2,
                reason="stale update",
            )
        )
        is None,
    )

    try:
        await repository.save(
            _integration(
                number=4,
                tenant_id=TENANT_A_ID,
                external_account_id="seller-1",
                source_url="https://ggsel.net/catalog/other",
            )
        )
    except RepositoryIdentityConflictError:
        verifier.check("duplicate external account is rejected per tenant", True)
    else:
        verifier.check("duplicate external account is rejected per tenant", False)

    try:
        await repository.save(
            _integration(
                number=5,
                tenant_id=TENANT_A_ID,
                external_account_id="seller-5",
                source_url="https://ggsel.net/catalog/minecraft",
            )
        )
    except RepositoryIdentityConflictError:
        verifier.check("duplicate source URL is rejected per tenant", True)
    else:
        verifier.check("duplicate source URL is rejected per tenant", False)


async def _verify_fresh_session_persistence(
    session: AsyncSession,
    verifier: Verification,
) -> None:
    repository = create_postgres_provider(session).marketplace_integrations
    rows = await repository.list_by_tenant(TENANT_A_ID)
    verifier.check("fresh-session integration persistence", len(rows) == 2)
    credential_rows = [
        integration for integration in rows if integration.credential is not None
    ]
    verifier.check(
        "fresh-session credential metadata persistence",
        len(credential_rows) == 1
        and credential_rows[0].credential is not None
        and credential_rows[0].credential.version == 1,
    )


async def _verify_rollback(
    session: AsyncSession,
    verifier: Verification,
) -> None:
    repository = create_postgres_provider(session).marketplace_integrations
    try:
        async with session.begin():
            await repository.save(
                _integration(
                    number=9,
                    tenant_id=TENANT_A_ID,
                    external_account_id="rollback-seller",
                    source_url="https://ggsel.net/catalog/rollback",
                )
            )
            raise RuntimeError("forced rollback")
    except RuntimeError:
        pass

    after_rollback = await repository.list_by_tenant(TENANT_A_ID)
    verifier.check("rollback leaves no partial integration", len(after_rollback) == 2)

    target = after_rollback[0]
    previous_version = target.version
    await session.rollback()
    try:
        async with session.begin():
            await repository.update_credential_reference(
                CredentialRotationIntent(
                    tenant_id=TENANT_A_ID,
                    integration_id=target.id,
                    auth_type=MarketplaceAuthType.API_KEY,
                    credential=_credential(number=30),
                    actor_id="admin-1",
                    requested_at=NOW + timedelta(minutes=31),
                    expected_version=previous_version,
                    reason="rollback credential update",
                )
            )
            raise RuntimeError("forced credential rollback")
    except RuntimeError:
        pass

    after_credential_rollback = await repository.get_by_tenant_and_id(
        TENANT_A_ID,
        target.id,
    )
    verifier.check(
        "rollback leaves no partial credential update",
        after_credential_rollback is not None
        and after_credential_rollback.version == previous_version,
    )


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


def _integration(
    *,
    number: int,
    tenant_id: UUID,
    display_name: str | None = None,
    enabled: bool = True,
    status: MarketplaceIntegrationStatus = MarketplaceIntegrationStatus.ACTIVE,
    external_account_id: str | None,
    source_url: str | None,
    version: int = 1,
) -> MarketplaceIntegration:
    timestamp = NOW + timedelta(minutes=number)
    return MarketplaceIntegration(
        id=UUID(int=18_000 + number),
        tenant_id=tenant_id,
        marketplace="ggsel",
        display_name=display_name or f"GGSEL {number}",
        enabled=enabled,
        status=status,
        external_account_id=external_account_id,
        source_url=source_url,
        auth_type=MarketplaceAuthType.NONE,
        created_at=timestamp,
        updated_at=timestamp,
        version=version,
    )


def _credential(*, number: int) -> MarketplaceCredentialMetadata:
    return MarketplaceCredentialMetadata(
        reference=f"secret://tenant-a/ggsel/{number}",
        configured_at=NOW + timedelta(minutes=number),
        version=1,
    )


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
