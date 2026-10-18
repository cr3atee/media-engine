"""Verify polling-history retention parity against isolated PostgreSQL."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from alembic import command

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATABASE_URL_ENV = "EPIC21_RETENTION_DATABASE_URL"
_CONFIGURED_DATABASE_URL = os.getenv(DATABASE_URL_ENV, "").strip()
if _CONFIGURED_DATABASE_URL:
    os.environ["DATABASE_URL"] = _CONFIGURED_DATABASE_URL

from app.database.repository_scope import create_postgres_repository_scope
from app.domain.marketplace_integrations import (
    MarketplaceIntegration,
    MarketplaceIntegrationStatus,
)
from app.domain.marketplace_polling import (
    MarketplacePollingRun,
    MarketplacePollingRunStatus,
)
from app.domain.tenancy import Tenant
from app.repositories.marketplace_polling_runs import (
    MarketplacePollingRunPruneRequest,
)
from app.repositories.provider import create_memory_provider
from app.services.marketplace_polling_retention import (
    MarketplacePollingRetentionPolicy,
    MarketplacePollingRetentionService,
)
from app.services.repository_scope import (
    RepositoryScopeFactory,
    create_memory_repository_scope,
)

TENANT_ID = UUID("55000000-0000-4000-8000-000000000001")
FOREIGN_TENANT_ID = UUID("55000000-0000-4000-8000-000000000002")
ROLLBACK_TENANT_ID = UUID("55000000-0000-4000-8000-000000000003")
CONCURRENT_TENANT_ID = UUID("55000000-0000-4000-8000-000000000004")
FIRST_INTEGRATION_ID = UUID("55000000-0000-4000-8000-000000000011")
SECOND_INTEGRATION_ID = UUID("55000000-0000-4000-8000-000000000012")
FOREIGN_INTEGRATION_ID = UUID("55000000-0000-4000-8000-000000000013")
ROLLBACK_INTEGRATION_ID = UUID("55000000-0000-4000-8000-000000000014")
CONCURRENT_INTEGRATION_ID = UUID("55000000-0000-4000-8000-000000000015")
NOW = datetime(2026, 10, 18, 8, 0, tzinfo=UTC)
POLICY = MarketplacePollingRetentionPolicy(
    retain_for=timedelta(days=30),
    keep_latest_per_integration=2,
    batch_size=3,
)


class Verification:
    """Collect named PostgreSQL retention checks."""

    def __init__(self) -> None:
        self.passed: list[str] = []

    def check(self, name: str, condition: bool) -> None:
        """Record one successful assertion or stop immediately."""
        if not condition:
            raise AssertionError(name)
        self.passed.append(name)
        print(f"PASS: {name}")


async def main() -> int:
    """Run guarded polling-retention verification."""
    database_url = _CONFIGURED_DATABASE_URL
    if not database_url:
        print(f"SKIPPED: set {DATABASE_URL_ENV} to an isolated PostgreSQL URL.")
        return 0
    _require_isolated_database(database_url)
    verifier = Verification()

    await _recreate_schema(database_url)
    await asyncio.to_thread(_apply_migrations, database_url)
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    scope_factory = create_postgres_repository_scope(session_factory)
    try:
        await _seed(scope_factory)
        await _verify_memory_postgres_parity(scope_factory, verifier)
        await _verify_tenant_isolation(scope_factory, verifier)
        await _verify_rollback(scope_factory, verifier)
        await _verify_concurrency(scope_factory, verifier)
        await _verify_schema(engine, verifier)
    finally:
        await engine.dispose()

    await _verify_fresh_engine(database_url, verifier)
    print()
    print(
        "Polling retention PostgreSQL verification passed: "
        f"{len(verifier.passed)}/{len(verifier.passed)} checks."
    )
    return 0


async def _seed(scope_factory: RepositoryScopeFactory) -> None:
    async with scope_factory() as repositories:
        for tenant in (
            _tenant(TENANT_ID, "retention-main"),
            _tenant(FOREIGN_TENANT_ID, "retention-foreign"),
            _tenant(ROLLBACK_TENANT_ID, "retention-rollback"),
            _tenant(CONCURRENT_TENANT_ID, "retention-concurrent"),
        ):
            await repositories.tenants.create(tenant)
        for integration in (
            _integration(TENANT_ID, FIRST_INTEGRATION_ID, "ggsel"),
            _integration(TENANT_ID, SECOND_INTEGRATION_ID, "playerok"),
            _integration(FOREIGN_TENANT_ID, FOREIGN_INTEGRATION_ID, "funpay"),
            _integration(ROLLBACK_TENANT_ID, ROLLBACK_INTEGRATION_ID, "ggsel"),
            _integration(
                CONCURRENT_TENANT_ID,
                CONCURRENT_INTEGRATION_ID,
                "playerok",
            ),
        ):
            await repositories.marketplace_integrations.save(integration)
        for run in (
            *_main_runs(),
            *_foreign_runs(),
            *_rollback_runs(),
            *_concurrent_runs(),
        ):
            await repositories.marketplace_polling_runs.save(run)


async def _verify_memory_postgres_parity(
    postgres_scope: RepositoryScopeFactory,
    verifier: Verification,
) -> None:
    memory_provider = create_memory_provider()
    for run in _main_runs():
        await memory_provider.marketplace_polling_runs.save(run)
    memory_service = MarketplacePollingRetentionService(
        repository_scope_factory=create_memory_repository_scope(memory_provider),
        policy=POLICY,
    )
    postgres_service = MarketplacePollingRetentionService(
        repository_scope_factory=postgres_scope,
        policy=POLICY,
    )

    memory_first = await memory_service.prune(TENANT_ID, now=NOW)
    postgres_first = await postgres_service.prune(TENANT_ID, now=NOW)
    expected_first = (
        _main_runs()[4].id,
        _main_runs()[0].id,
        _main_runs()[1].id,
    )
    verifier.check(
        "memory and PostgreSQL select the same first batch",
        memory_first.deleted_run_ids
        == postgres_first.deleted_run_ids
        == expected_first,
    )
    verifier.check(
        "first pass reports its explicit batch bound",
        memory_first.batch_limit_reached and postgres_first.batch_limit_reached,
    )
    verifier.check(
        "retention cutoff is deterministic",
        postgres_first.cutoff == NOW - timedelta(days=30),
    )

    memory_second = await memory_service.prune(TENANT_ID, now=NOW)
    postgres_second = await postgres_service.prune(TENANT_ID, now=NOW)
    verifier.check(
        "memory and PostgreSQL select the same remainder",
        memory_second.deleted_run_ids
        == postgres_second.deleted_run_ids
        == (_main_runs()[5].id,),
    )
    verifier.check(
        "partial final batch is reported accurately",
        not memory_second.batch_limit_reached
        and not postgres_second.batch_limit_reached,
    )
    memory_final = await memory_service.prune(TENANT_ID, now=NOW)
    postgres_final = await postgres_service.prune(TENANT_ID, now=NOW)
    verifier.check(
        "completed pruning is idempotent",
        memory_final.deleted_count == postgres_final.deleted_count == 0,
    )

    async with postgres_scope() as repositories:
        first_remaining = (
            await repositories.marketplace_polling_runs.list_by_integration(
                TENANT_ID,
                FIRST_INTEGRATION_ID,
                limit=100,
            )
        )
        second_remaining = (
            await repositories.marketplace_polling_runs.list_by_integration(
                TENANT_ID,
                SECOND_INTEGRATION_ID,
                limit=100,
            )
        )
    verifier.check(
        "latest runs remain protected per integration",
        tuple(run.id for run in first_remaining)
        == (_main_runs()[3].id, _main_runs()[2].id)
        and tuple(run.id for run in second_remaining)
        == (_main_runs()[7].id, _main_runs()[6].id),
    )


async def _verify_tenant_isolation(
    scope_factory: RepositoryScopeFactory,
    verifier: Verification,
) -> None:
    async with scope_factory() as repositories:
        foreign = await repositories.marketplace_polling_runs.list_by_integration(
            FOREIGN_TENANT_ID,
            FOREIGN_INTEGRATION_ID,
            limit=100,
        )
        cross_tenant = await repositories.marketplace_polling_runs.list_by_integration(
            TENANT_ID,
            FOREIGN_INTEGRATION_ID,
            limit=100,
        )
    verifier.check(
        "foreign tenant history is not pruned",
        tuple(foreign) == tuple(reversed(_foreign_runs())),
    )
    verifier.check("cross-tenant lookup remains empty", not cross_tenant)


async def _verify_rollback(
    scope_factory: RepositoryScopeFactory,
    verifier: Verification,
) -> None:
    before = await _history(
        scope_factory,
        ROLLBACK_TENANT_ID,
        ROLLBACK_INTEGRATION_ID,
    )
    try:
        async with scope_factory() as repositories:
            deleted = await repositories.marketplace_polling_runs.prune_by_tenant(
                MarketplacePollingRunPruneRequest(
                    tenant_id=ROLLBACK_TENANT_ID,
                    cutoff=NOW - timedelta(days=30),
                    keep_latest_per_integration=1,
                    limit=10,
                )
            )
            if len(deleted) != 3:
                raise AssertionError("rollback precondition")
            raise RuntimeError("controlled rollback")
    except RuntimeError as error:
        if str(error) != "controlled rollback":
            raise
    else:
        raise AssertionError("controlled rollback must raise")
    after = await _history(
        scope_factory,
        ROLLBACK_TENANT_ID,
        ROLLBACK_INTEGRATION_ID,
    )
    verifier.check("PostgreSQL pruning rolls back atomically", after == before)


async def _verify_concurrency(
    scope_factory: RepositoryScopeFactory,
    verifier: Verification,
) -> None:
    policy = MarketplacePollingRetentionPolicy(
        retain_for=timedelta(days=30),
        keep_latest_per_integration=1,
        batch_size=3,
    )
    services = (
        MarketplacePollingRetentionService(
            repository_scope_factory=scope_factory,
            policy=policy,
        ),
        MarketplacePollingRetentionService(
            repository_scope_factory=scope_factory,
            policy=policy,
        ),
    )
    first, second = await asyncio.gather(
        services[0].prune(CONCURRENT_TENANT_ID, now=NOW),
        services[1].prune(CONCURRENT_TENANT_ID, now=NOW),
    )
    first_ids = set(first.deleted_run_ids)
    second_ids = set(second.deleted_run_ids)
    verifier.check(
        "concurrent workers never report the same deletion",
        first_ids.isdisjoint(second_ids),
    )

    all_deleted = first_ids | second_ids
    while True:
        result = await services[0].prune(CONCURRENT_TENANT_ID, now=NOW)
        duplicate_ids = all_deleted.intersection(result.deleted_run_ids)
        if duplicate_ids:
            raise AssertionError("deleted polling IDs must not repeat")
        all_deleted.update(result.deleted_run_ids)
        if not result.batch_limit_reached:
            break
    expected_deleted = {run.id for run in _concurrent_runs()[:-1]}
    verifier.check(
        "concurrent pruning eventually removes every eligible run",
        all_deleted == expected_deleted,
    )
    remaining = await _history(
        scope_factory,
        CONCURRENT_TENANT_ID,
        CONCURRENT_INTEGRATION_ID,
    )
    verifier.check(
        "concurrent pruning preserves the newest run",
        tuple(run.id for run in remaining) == (_concurrent_runs()[-1].id,),
    )


async def _verify_schema(engine: AsyncEngine, verifier: Verification) -> None:
    async with engine.connect() as connection:
        revision = await connection.scalar(
            text("SELECT version_num FROM alembic_version")
        )
        indexes = set(
            (
                await connection.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE tablename = 'marketplace_polling_runs'"
                    )
                )
            ).scalars()
        )
    verifier.check("current Alembic head is applied", revision == _migration_head())
    verifier.check(
        "existing integration history index supports retention ranking",
        "ix_marketplace_polling_runs_integration_finished" in indexes,
    )


async def _verify_fresh_engine(
    database_url: str,
    verifier: Verification,
) -> None:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    scope_factory = create_postgres_repository_scope(session_factory)
    try:
        remaining = await _history(
            scope_factory,
            TENANT_ID,
            FIRST_INTEGRATION_ID,
        )
        verifier.check(
            "retention survives a fresh engine and session",
            tuple(run.id for run in remaining)
            == (_main_runs()[3].id, _main_runs()[2].id),
        )
    finally:
        await engine.dispose()


async def _history(
    scope_factory: RepositoryScopeFactory,
    tenant_id: UUID,
    integration_id: UUID,
) -> tuple[MarketplacePollingRun, ...]:
    async with scope_factory() as repositories:
        return tuple(
            await repositories.marketplace_polling_runs.list_by_integration(
                tenant_id,
                integration_id,
                limit=100,
            )
        )


def _tenant(tenant_id: UUID, slug: str) -> Tenant:
    return Tenant(
        id=tenant_id,
        name=slug.replace("-", " ").title(),
        slug=slug,
        created_at=NOW,
        updated_at=NOW,
    )


def _integration(
    tenant_id: UUID,
    integration_id: UUID,
    marketplace: str,
) -> MarketplaceIntegration:
    return MarketplaceIntegration(
        id=integration_id,
        tenant_id=tenant_id,
        marketplace=marketplace,
        display_name=f"{marketplace} retention verification",
        source_url=f"https://example.invalid/{marketplace}",
        enabled=True,
        status=MarketplaceIntegrationStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )


def _main_runs() -> tuple[MarketplacePollingRun, ...]:
    return (
        _run(1, TENANT_ID, FIRST_INTEGRATION_ID, 100),
        _run(2, TENANT_ID, FIRST_INTEGRATION_ID, 80),
        _run(3, TENANT_ID, FIRST_INTEGRATION_ID, 20),
        _run(4, TENANT_ID, FIRST_INTEGRATION_ID, 1),
        _run(5, TENANT_ID, SECOND_INTEGRATION_ID, 120),
        _run(6, TENANT_ID, SECOND_INTEGRATION_ID, 70),
        _run(7, TENANT_ID, SECOND_INTEGRATION_ID, 15),
        _run(8, TENANT_ID, SECOND_INTEGRATION_ID, 2),
    )


def _foreign_runs() -> tuple[MarketplacePollingRun, ...]:
    return tuple(
        _run(100 + number, FOREIGN_TENANT_ID, FOREIGN_INTEGRATION_ID, 200 - number)
        for number in range(1, 5)
    )


def _rollback_runs() -> tuple[MarketplacePollingRun, ...]:
    return tuple(
        _run(
            200 + number,
            ROLLBACK_TENANT_ID,
            ROLLBACK_INTEGRATION_ID,
            150 - number,
        )
        for number in range(1, 5)
    )


def _concurrent_runs() -> tuple[MarketplacePollingRun, ...]:
    return tuple(
        _run(
            300 + number,
            CONCURRENT_TENANT_ID,
            CONCURRENT_INTEGRATION_ID,
            120 - number,
        )
        for number in range(1, 7)
    )


def _run(
    number: int,
    tenant_id: UUID,
    integration_id: UUID,
    days_ago: int,
) -> MarketplacePollingRun:
    finished_at = NOW - timedelta(days=days_ago)
    return MarketplacePollingRun(
        id=UUID(int=55_000 + number),
        tenant_id=tenant_id,
        integration_id=integration_id,
        marketplace="ggsel",
        status=MarketplacePollingRunStatus.SUCCEEDED,
        started_at=finished_at - timedelta(seconds=2),
        finished_at=finished_at,
        offers_received=10,
        offers_persisted=10,
    )


async def _recreate_schema(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


def _apply_migrations(database_url: str) -> None:
    command.upgrade(_alembic_config(database_url), "head")


def _migration_head() -> str:
    return ScriptDirectory.from_config(_alembic_config()).get_current_head() or ""


def _alembic_config(database_url: str | None = None) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    if database_url is not None:
        config.set_main_option("sqlalchemy.url", database_url)
    return config


def _require_isolated_database(database_url: str) -> None:
    url = make_url(database_url)
    database = url.database or ""
    if not database.startswith("epic21_retention_"):
        raise RuntimeError(
            "Polling retention verification requires an epic21_retention_* database."
        )
    if url.host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("Polling retention verification requires local PostgreSQL.")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
