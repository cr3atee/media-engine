"""Verify durable marketplace polling history against isolated PostgreSQL."""

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
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATABASE_URL_ENV = "EPIC19_POLLING_HISTORY_DATABASE_URL"
_CONFIGURED_DATABASE_URL = os.getenv(DATABASE_URL_ENV, "").strip()
if _CONFIGURED_DATABASE_URL:
    os.environ["DATABASE_URL"] = _CONFIGURED_DATABASE_URL

from app.database.repository_scope import create_postgres_repository_scope
from app.database.session import engine as default_engine
from app.domain.marketplace import Marketplace
from app.domain.marketplace_integrations import (
    MarketplaceIntegration,
    MarketplaceIntegrationStatus,
)
from app.domain.marketplace_polling import MarketplacePollingRunStatus
from app.domain.tenancy import Tenant
from app.repositories.base import RepositoryIdentityConflictError
from app.services.marketplace_application_runner import MarketplaceRunResult
from app.services.marketplace_integration_execution import (
    MarketplaceIntegrationExecutionService,
)
from app.services.repository_scope import RepositoryScopeFactory

TENANT_ID = UUID("48000000-0000-4000-8000-000000000001")
FOREIGN_TENANT_ID = UUID("48000000-0000-4000-8000-000000000002")
SUCCESS_ID = UUID("48000000-0000-4000-8000-000000000011")
FAILURE_ID = UUID("48000000-0000-4000-8000-000000000012")
SKIPPED_ID = UUID("48000000-0000-4000-8000-000000000013")
NOW = datetime(2026, 10, 6, 10, 0, tzinfo=UTC)


class Verification:
    """Collect named polling-history checks."""

    def __init__(self) -> None:
        self.passed: list[str] = []

    def check(self, name: str, condition: bool) -> None:
        if not condition:
            raise AssertionError(name)
        self.passed.append(name)
        print(f"PASS: {name}")


class VerificationClock:
    """Return deterministic increasing UTC timestamps."""

    def __init__(self, *, offset_seconds: int = 0) -> None:
        self._calls = 0
        self._offset_seconds = offset_seconds

    def __call__(self) -> datetime:
        value = NOW + timedelta(
            minutes=10,
            seconds=self._offset_seconds + self._calls,
        )
        self._calls += 1
        return value


class SuccessfulRunner:
    """Return one production-shaped application result without network access."""

    async def run(self, url: str) -> MarketplaceRunResult:
        del url
        return MarketplaceRunResult(
            marketplace=Marketplace.GGSEL,
            offers_received=5,
            offers_persisted=5,
            comparison_results=0,
            snapshots_created=5,
            snapshots_persisted=5,
            skipped_offers=0,
            price_changes_detected=2,
            event_candidates_built=2,
            events_created=2,
            events_existing=0,
            skipped_event_candidates=0,
            event_ids=(),
            events_scored=0,
            content_items_generated=0,
            persistence_committed=True,
            errors=("source item omitted",),
            tenant_id=TENANT_ID,
        )


class FailingRunner:
    """Fail with private-looking input to prove persisted diagnostics are safe."""

    async def run(self, url: str) -> object:
        raise TimeoutError(f"secret=never-store; url={url}")


class RunIdFactory:
    """Produce deterministic run identifiers for verification."""

    def __init__(self, start: int = 48_100) -> None:
        self._next = start

    def __call__(self) -> UUID:
        value = UUID(int=self._next)
        self._next += 1
        return value


async def main() -> int:
    """Run the isolated PostgreSQL polling-history verification."""
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
        service = _service(scope_factory)
        first = await service.run_enabled_integrations()
        second = await service.run_enabled_integrations()

        verifier.check(
            "three enabled integrations are selected", first.selected_integrations == 3
        )
        verifier.check("success and failure execute", first.executed_integrations == 2)
        verifier.check(
            "missing URL is retained as skipped", first.skipped_integrations == 1
        )
        verifier.check("failure remains isolated", first.failed_integrations == 1)
        verifier.check(
            "second polling batch also completes", len(second.executions) == 3
        )

        await _verify_repository(scope_factory, verifier)
        await _verify_schema(engine, verifier)
        await _verify_atomic_rollback(scope_factory, verifier)
    finally:
        await engine.dispose()
        await default_engine.dispose()

    await _verify_fresh_engine(database_url, verifier)
    print()
    print(
        "Marketplace polling history PostgreSQL verification: "
        f"{len(verifier.passed)} checks passed."
    )
    return 0


def _service(
    scope_factory: RepositoryScopeFactory,
    *,
    run_id_factory: RunIdFactory | None = None,
    clock: VerificationClock | None = None,
) -> MarketplaceIntegrationExecutionService:
    return MarketplaceIntegrationExecutionService(
        repository_scope_factory=scope_factory,
        runner_factories={
            "ggsel": lambda integration: SuccessfulRunner(),
            "playerok": lambda integration: FailingRunner(),
        },
        clock=clock or VerificationClock(),
        polling_run_id_factory=run_id_factory or RunIdFactory(),
    )


async def _seed(scope_factory: RepositoryScopeFactory) -> None:
    async with scope_factory() as repositories:
        await repositories.tenants.create(
            Tenant(
                id=TENANT_ID,
                name="Polling tenant",
                slug="polling-tenant",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await repositories.tenants.create(
            Tenant(
                id=FOREIGN_TENANT_ID,
                name="Foreign tenant",
                slug="foreign-tenant",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        for integration in (
            _integration(SUCCESS_ID, "ggsel", "https://example.test/ggsel"),
            _integration(FAILURE_ID, "playerok", "https://example.test/private"),
            _integration(SKIPPED_ID, "funpay", None),
        ):
            await repositories.marketplace_integrations.save(integration)


def _integration(
    integration_id: UUID,
    marketplace: str,
    source_url: str | None,
) -> MarketplaceIntegration:
    return MarketplaceIntegration(
        id=integration_id,
        tenant_id=TENANT_ID,
        marketplace=marketplace,
        display_name=f"{marketplace} verification",
        enabled=True,
        status=MarketplaceIntegrationStatus.ACTIVE,
        source_url=source_url,
        created_at=NOW,
        updated_at=NOW,
    )


async def _verify_repository(
    scope_factory: RepositoryScopeFactory,
    verifier: Verification,
) -> None:
    async with scope_factory() as repositories:
        successes = await repositories.marketplace_polling_runs.list_by_integration(
            TENANT_ID,
            SUCCESS_ID,
            limit=10,
        )
        failures = await repositories.marketplace_polling_runs.list_by_integration(
            TENANT_ID,
            FAILURE_ID,
            limit=10,
        )
        skipped = await repositories.marketplace_polling_runs.list_by_integration(
            TENANT_ID,
            SKIPPED_ID,
            limit=10,
        )
        foreign = await repositories.marketplace_polling_runs.list_by_integration(
            FOREIGN_TENANT_ID,
            SUCCESS_ID,
            limit=10,
        )
        limited = await repositories.marketplace_polling_runs.list_by_integration(
            TENANT_ID,
            SUCCESS_ID,
            limit=1,
        )
        success_integration = (
            await repositories.marketplace_integrations.get_by_tenant_and_id(
                TENANT_ID,
                SUCCESS_ID,
            )
        )
        failed_integration = (
            await repositories.marketplace_integrations.get_by_tenant_and_id(
                TENANT_ID,
                FAILURE_ID,
            )
        )

    verifier.check("two successful runs are retained", len(successes) == 2)
    verifier.check(
        "successful metrics are retained",
        all(
            run.status is MarketplacePollingRunStatus.SUCCEEDED
            and run.offers_received == 5
            and run.snapshots_persisted == 5
            and run.processing_error_count == 1
            for run in successes
        ),
    )
    verifier.check(
        "newest-first ordering is deterministic",
        successes[0].finished_at > successes[1].finished_at,
    )
    verifier.check("bounded reads honor limit", tuple(limited) == (successes[0],))
    verifier.check("tenant isolation hides foreign history", not foreign)
    verifier.check(
        "failures retain safe classification",
        len(failures) == 2
        and all(run.status is MarketplacePollingRunStatus.FAILED for run in failures)
        and all(run.error_code == "TimeoutError" for run in failures),
    )
    verifier.check(
        "failure diagnostics redact exception and URL",
        all(run.error_summary == "Marketplace polling failed." for run in failures)
        and all("secret" not in (run.error_summary or "") for run in failures)
        and all("example.test" not in (run.error_summary or "") for run in failures),
    )
    verifier.check(
        "skipped runs retain only stable reason",
        len(skipped) == 2
        and all(run.status is MarketplacePollingRunStatus.SKIPPED for run in skipped)
        and all(run.skipped_reason == "missing_source_url" for run in skipped),
    )
    verifier.check(
        "latest success metadata advances with history",
        success_integration is not None
        and success_integration.last_successful_run_at == successes[0].finished_at
        and success_integration.version == 3,
    )
    verifier.check(
        "latest failure metadata advances with history",
        failed_integration is not None
        and failed_integration.last_failed_run_at == failures[0].finished_at
        and failed_integration.last_error_code == "TimeoutError"
        and failed_integration.version == 3,
    )


async def _verify_schema(engine: AsyncEngine, verifier: Verification) -> None:
    async with engine.connect() as connection:
        revision = await connection.scalar(
            text("SELECT version_num FROM alembic_version")
        )
        constraints = set(
            (
                await connection.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conrelid IN "
                        "('marketplace_integrations'::regclass, "
                        "'marketplace_polling_runs'::regclass)"
                    )
                )
            ).scalars()
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
        columns = set(
            (
                await connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'marketplace_polling_runs'"
                    )
                )
            ).scalars()
        )

    verifier.check(
        "Alembic polling-history head is applied", revision == _migration_head()
    )
    verifier.check(
        "tenant/integration composite foreign key exists",
        "fk_marketplace_polling_runs_integration" in constraints,
    )
    verifier.check(
        "integration composite identity exists",
        "uq_marketplace_integrations_tenant_id" in constraints,
    )
    verifier.check(
        "outcome integrity check exists",
        "ck_marketplace_polling_runs_outcome" in constraints,
    )
    verifier.check(
        "history lookup index exists",
        "ix_marketplace_polling_runs_integration_finished" in indexes,
    )
    verifier.check(
        "polling table cannot store source URLs or credentials",
        "source_url" not in columns and "credential_reference" not in columns,
    )


async def _verify_atomic_rollback(
    scope_factory: RepositoryScopeFactory,
    verifier: Verification,
) -> None:
    async with scope_factory() as repositories:
        before = await repositories.marketplace_integrations.get_by_tenant_and_id(
            TENANT_ID,
            SUCCESS_ID,
        )
        history = await repositories.marketplace_polling_runs.list_by_integration(
            TENANT_ID,
            SUCCESS_ID,
            limit=10,
        )
    if before is None or not history:
        raise AssertionError("rollback precondition")

    collision = RunIdFactory(start=history[-1].id.int)
    try:
        await _service(
            scope_factory,
            run_id_factory=collision,
            clock=VerificationClock(offset_seconds=100),
        ).run_enabled_integrations()
    except RepositoryIdentityConflictError:
        pass
    else:
        raise AssertionError("immutable run collision must fail")

    async with scope_factory() as repositories:
        after = await repositories.marketplace_integrations.get_by_tenant_and_id(
            TENANT_ID,
            SUCCESS_ID,
        )
        after_history = await repositories.marketplace_polling_runs.list_by_integration(
            TENANT_ID,
            SUCCESS_ID,
            limit=10,
        )
    verifier.check("history identity collision is rejected", after is not None)
    verifier.check("latest outcome update rolls back atomically", after == before)
    verifier.check(
        "failed transaction appends no history", tuple(after_history) == tuple(history)
    )


async def _verify_fresh_engine(database_url: str, verifier: Verification) -> None:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    scope_factory = create_postgres_repository_scope(session_factory)
    try:
        async with scope_factory() as repositories:
            runs = await repositories.marketplace_polling_runs.list_by_integration(
                TENANT_ID,
                SUCCESS_ID,
                limit=10,
            )
        verifier.check("polling history survives fresh engine", len(runs) == 2)
    finally:
        await engine.dispose()


async def _recreate_schema(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


def _apply_migrations(database_url: str) -> None:
    config = _alembic_config(database_url)
    command.upgrade(config, "head")


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
    if not database.startswith("epic19_history_"):
        raise RuntimeError(
            "Polling-history verification requires an epic19_history_* database."
        )
    if url.host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("Polling-history verification requires local PostgreSQL.")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
