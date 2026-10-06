"""Verify guarded live marketplace polling against isolated PostgreSQL."""

# ruff: noqa: E402, I001

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATABASE_URL_ENV = "EPIC19_POLLING_DATABASE_URL"
_CONFIGURED_DATABASE_URL = os.getenv(DATABASE_URL_ENV, "").strip()
if _CONFIGURED_DATABASE_URL:
    os.environ["DATABASE_URL"] = _CONFIGURED_DATABASE_URL

from app.config.settings import SchedulerSettings
from app.core.http_client import HttpClient
from app.database.repository_scope import create_postgres_repository_scope
from app.domain.marketplace_integrations import (
    MarketplaceIntegration,
    MarketplaceIntegrationStatus,
)
from app.domain.tenancy import Tenant
from app.runtime.bootstrap import create_postgres_runtime_components
from app.runtime.marketplaces import create_marketplace_runner_factories
from app.runtime.monitoring import RuntimeMonitor
from app.runtime.process import RuntimeJobConfig, RuntimeProcess
from app.runtime.worker import register_enabled_marketplace_integrations_job
from app.scheduler.jobs import JobExecutionState
from app.services.marketplace_application_runner import MarketplaceRunResult
from app.services.marketplace_integration_execution import (
    MarketplaceIntegrationExecutionBatch,
    MarketplaceIntegrationRunner,
)
from app.services.repository_scope import RepositoryScopeFactory

TENANT_ID = UUID("47000000-0000-4000-8000-000000000001")
NOW = datetime.now(UTC) - timedelta(minutes=5)
GGSEL_URL = "https://ggsel.net/en/catalog/minecraft-keys-pc"
PLAYEROK_URL = (
    "https://playerok.com/graphql?first=20"
    "&game_id=1ecc48ce-4f1a-6533-28cc-9d8eecf47287"
    "&game_category_id=1eeb53e1-112a-6b20-fffc-80e79d6ff930"
)
FUNPAY_URL = "https://funpay.com/lots/4176/"
JOB_NAME = "enabled-marketplace-integrations"
MAX_POLLING_ATTEMPTS = 3
REAL_MARKETPLACES = ("ggsel", "playerok", "funpay")


class Verification:
    """Collect named live polling checks."""

    def __init__(self) -> None:
        self.passed: list[str] = []

    def check(self, name: str, condition: bool) -> None:
        """Record a passing condition or raise its diagnostic name."""
        if not condition:
            raise AssertionError(name)
        self.passed.append(name)
        print(f"PASS: {name}")


class IntentionalFailureRunner:
    """Verifier-only runner proving that one source failure is isolated."""

    async def run(self, url: str) -> object:
        """Raise a diagnostic containing data that must never be reported."""
        raise RuntimeError(f"intentional-private-value:{url}")


async def main() -> int:
    """Run bounded production-shaped live polling and verify persistence."""
    _configure_stdout()
    logging.getLogger("httpx").setLevel(logging.WARNING)
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
        await _seed_integrations(scope_factory)
        components = create_postgres_runtime_components(
            SchedulerSettings(lease_enabled=False, tick_seconds=0.1),
            session_factory=session_factory,
        )
        process = RuntimeProcess(components)

        async with HttpClient(timeout=45.0) as http_client:
            factories = dict(
                create_marketplace_runner_factories(
                    http_client=http_client,
                    repository_scope_factory=scope_factory,
                )
            )
            factories["failure-probe"] = _failure_factory
            register_enabled_marketplace_integrations_job(
                process,
                runner_factories=factories,
                config=RuntimeJobConfig(enabled=False, timeout_seconds=900.0),
            )
            successful_marketplaces: set[str] = set()
            polling_attempts = 0
            while (
                polling_attempts < MAX_POLLING_ATTEMPTS
                and successful_marketplaces != set(REAL_MARKETPLACES)
            ):
                polling_attempts += 1
                await process.execute_once(JOB_NAME)
                batch = _require_batch(process)
                _verify_batch_shape(batch, polling_attempts, verifier)
                for execution in batch.executions:
                    if execution.marketplace not in REAL_MARKETPLACES:
                        continue
                    if execution.succeeded:
                        verifier.check(
                            f"{execution.marketplace} polling attempt "
                            f"{polling_attempts} produces application input",
                            isinstance(execution.result, MarketplaceRunResult)
                            and execution.result.offers_received > 0
                            and execution.result.offers_persisted > 0
                            and execution.result.snapshots_persisted > 0,
                        )
                        successful_marketplaces.add(execution.marketplace)
                    else:
                        print(
                            "OBSERVED: "
                            f"{execution.marketplace} attempt {polling_attempts} "
                            f"failed as {execution.error_code}."
                        )
                if successful_marketplaces != set(REAL_MARKETPLACES):
                    await asyncio.sleep(2.0)

        verifier.check(
            "every real marketplace succeeds within bounded polling ticks",
            successful_marketplaces == set(REAL_MARKETPLACES),
        )
        _verify_scheduler_statistics(process, polling_attempts, verifier)
        await _verify_persistence(
            scope_factory,
            engine,
            polling_attempts,
            verifier,
        )
    finally:
        await engine.dispose()

    await _verify_fresh_engine(database_url, verifier)
    print()
    print(
        "Live marketplace polling PostgreSQL verification: "
        f"{len(verifier.passed)} checks passed."
    )
    return 0


def _require_batch(process: RuntimeProcess) -> MarketplaceIntegrationExecutionBatch:
    result = process.get_last_result(JOB_NAME)
    if not isinstance(result, MarketplaceIntegrationExecutionBatch):
        status = process.list_statuses()[0]
        raise RuntimeError(
            "Scheduler did not return marketplace batch: "
            f"state={status.state.value}, error={status.last_error}"
        )
    return result


def _verify_batch_shape(
    batch: MarketplaceIntegrationExecutionBatch,
    attempt: int,
    verifier: Verification,
) -> None:
    verifier.check(
        f"attempt {attempt} selects all enabled integrations",
        batch.selected_integrations == 4,
    )
    verifier.check(
        f"attempt {attempt} runs all selected integrations",
        batch.executed_integrations == 4,
    )
    verifier.check(
        f"attempt {attempt} skips no configured integration",
        batch.skipped_integrations == 0,
    )
    verifier.check(
        f"attempt {attempt} isolates failures inside the batch",
        batch.failed_integrations >= 1,
    )

    executions = {execution.marketplace: execution for execution in batch.executions}
    failed = executions["failure-probe"]
    verifier.check(
        f"attempt {attempt} classifies and sanitizes the failure probe",
        failed.error_code == "RuntimeError"
        and failed.error_summary == "Marketplace polling failed."
        and "intentional-private-value" not in repr(failed),
    )

    diagnostic = RuntimeMonitor().summarize_marketplace_batch(batch)
    verifier.check(
        f"attempt {attempt} runtime monitor reports failures",
        diagnostic.failed_integrations == batch.failed_integrations,
    )
    verifier.check(
        f"attempt {attempt} runtime diagnostics remain sanitized",
        "intentional-private-value" not in repr(diagnostic)
        and "127.0.0.1" not in repr(diagnostic),
    )


def _verify_scheduler_statistics(
    process: RuntimeProcess,
    polling_attempts: int,
    verifier: Verification,
) -> None:
    status = process.list_statuses()[0]
    statistics = process.list_statistics()[0]
    verifier.check(
        "Scheduler job completes despite one source failure",
        status.state is JobExecutionState.SUCCEEDED,
    )
    verifier.check(
        "Scheduler records every polling tick",
        statistics.successful_executions == polling_attempts
        and statistics.failed_executions == 0,
    )


async def _verify_persistence(
    scope_factory: RepositoryScopeFactory,
    engine: AsyncEngine,
    polling_attempts: int,
    verifier: Verification,
) -> None:
    # Runtime factories are intentionally exercised through their public scope;
    # SQL is used only for aggregate verification outside application behavior.
    async with scope_factory() as repositories:
        offers = await repositories.offers.list_by_tenant(TENANT_ID)
        integrations = await repositories.marketplace_integrations.list_by_tenant(
            TENANT_ID
        )

    offer_counts: dict[str, int] = {}
    for offer in offers:
        offer_counts[offer.marketplace] = offer_counts.get(offer.marketplace, 0) + 1
    verifier.check(
        "all live marketplaces persist offers",
        all(offer_counts.get(marketplace, 0) > 0 for marketplace in REAL_MARKETPLACES),
    )

    integration_by_marketplace = {
        integration.marketplace: integration for integration in integrations
    }
    for marketplace in REAL_MARKETPLACES:
        integration = integration_by_marketplace[marketplace]
        verifier.check(
            f"{marketplace} success metadata is durable",
            integration.last_successful_run_at is not None
            and integration.version == 1 + polling_attempts,
        )
    failed = integration_by_marketplace["failure-probe"]
    verifier.check(
        "failure metadata is durable and sanitized",
        failed.last_failed_run_at is not None
        and failed.last_error_code == "RuntimeError"
        and failed.last_error_summary == "Marketplace polling failed."
        and failed.version == 1 + polling_attempts,
    )

    async with engine.connect() as connection:
        snapshot_count = await connection.scalar(
            text("SELECT count(*) FROM price_snapshots WHERE tenant_id = :tenant_id"),
            {"tenant_id": TENANT_ID},
        )
        migration = await connection.scalar(
            text("SELECT version_num FROM alembic_version")
        )
    verifier.check(
        "live snapshots are committed",
        isinstance(snapshot_count, int) and snapshot_count > 0,
    )
    verifier.check("current Alembic head is applied", migration == _migration_head())


async def _verify_fresh_engine(database_url: str, verifier: Verification) -> None:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    scope_factory = create_postgres_repository_scope(session_factory)
    try:
        async with scope_factory() as repositories:
            offers = await repositories.offers.list_by_tenant(TENANT_ID)
            integrations = await repositories.marketplace_integrations.list_by_tenant(
                TENANT_ID
            )
        verifier.check("fresh engine reads committed live offers", len(offers) > 0)
        verifier.check(
            "fresh engine reads all integration outcomes",
            len(integrations) == 4
            and all(integration.version >= 2 for integration in integrations),
        )
    finally:
        await engine.dispose()


async def _seed_integrations(scope_factory: RepositoryScopeFactory) -> None:
    async with scope_factory() as repositories:
        await repositories.tenants.create(
            Tenant(
                id=TENANT_ID,
                name="EPIC 19 Live Polling Verification",
                slug="epic19-live-polling",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        for number, marketplace, source_url in (
            (1, "failure-probe", "https://127.0.0.1/private-source"),
            (2, "ggsel", GGSEL_URL),
            (3, "playerok", PLAYEROK_URL),
            (4, "funpay", FUNPAY_URL),
        ):
            timestamp = NOW + timedelta(seconds=number)
            await repositories.marketplace_integrations.save(
                MarketplaceIntegration(
                    id=UUID(int=47_000 + number),
                    tenant_id=TENANT_ID,
                    marketplace=marketplace,
                    display_name=f"{marketplace} verification",
                    source_url=source_url,
                    enabled=True,
                    status=MarketplaceIntegrationStatus.ACTIVE,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )


def _failure_factory(
    _integration: MarketplaceIntegration,
) -> MarketplaceIntegrationRunner:
    return IntentionalFailureRunner()


async def _recreate_schema(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


def _apply_migrations(database_url: str) -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def _migration_head() -> str:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        raise RuntimeError("Alembic has no current head revision.")
    return head


def _require_isolated_database(database_url: str) -> None:
    database_name = make_url(database_url).database or ""
    if not database_name.startswith("epic19_polling_"):
        msg = (
            f"{DATABASE_URL_ENV} must point to an isolated epic19_polling_* "
            f"database; got {database_name!r}."
        )
        raise RuntimeError(msg)


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
