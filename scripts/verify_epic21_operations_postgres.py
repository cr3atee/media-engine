"""Verify the production-shaped EPIC 21 runtime against isolated PostgreSQL."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATABASE_URL_ENV = "EPIC21_OPERATIONS_DATABASE_URL"
_CONFIGURED_DATABASE_URL = os.getenv(DATABASE_URL_ENV, "").strip()
if _CONFIGURED_DATABASE_URL:
    os.environ["DATABASE_URL"] = _CONFIGURED_DATABASE_URL

from app.config.settings import SchedulerSettings
from app.database.repository_scope import create_postgres_repository_scope
from app.database.session import engine as default_engine
from app.domain.marketplace import Marketplace
from app.domain.marketplace_integrations import (
    MarketplaceIntegration,
    MarketplaceIntegrationStatus,
)
from app.domain.marketplace_polling import (
    MarketplacePollingRun,
    MarketplacePollingRunStatus,
)
from app.domain.tenancy import Tenant
from app.repositories.postgres import PostgresSchedulerLeaseRepository
from app.runtime.alert_lifecycle import (
    AlertLifecycleNotification,
    OperationalAlertLifecycle,
)
from app.runtime.alert_monitor import RuntimeAlertMonitor
from app.runtime.bootstrap import (
    RuntimeComponents,
    create_postgres_runtime_components,
)
from app.runtime.metrics import PrometheusTextfileWriter, RuntimeMetricsExporter
from app.runtime.process import RuntimeJobConfig, RuntimeProcess
from app.runtime.worker import (
    register_enabled_marketplace_integrations_job,
    register_marketplace_polling_retention_job,
)
from app.scheduler.jobs import JobExecutionState
from app.services.marketplace_application_runner import MarketplaceRunResult
from app.services.marketplace_integration_execution import (
    MarketplaceIntegrationExecutionBatch,
    MarketplaceIntegrationRunner,
    MarketplaceIntegrationRunnerFactory,
)
from app.services.marketplace_polling_retention import (
    MarketplacePollingRetentionBatch,
)
from app.services.repository_scope import RepositoryScopeFactory

PRIMARY_TENANT_ID = UUID("57000000-0000-4000-8000-000000000001")
FOREIGN_TENANT_ID = UUID("57000000-0000-4000-8000-000000000002")
SUCCESS_INTEGRATION_ID = UUID("57000000-0000-4000-8000-000000000011")
FAILURE_INTEGRATION_ID = UUID("57000000-0000-4000-8000-000000000012")
SKIPPED_INTEGRATION_ID = UUID("57000000-0000-4000-8000-000000000013")
FOREIGN_INTEGRATION_ID = UUID("57000000-0000-4000-8000-000000000014")
ROLLBACK_RUN_ID = UUID("57000000-0000-4000-8000-000000000099")
CREATED_AT = datetime(2025, 1, 1, 10, 0, tzinfo=UTC)
PRIVATE_SOURCE_URL = "https://source.invalid/catalog?token=never-export"
PRIVATE_FAILURE = "credential=never-export"
POLLING_JOB = "enabled-marketplace-integrations"
RETENTION_JOB = "marketplace-polling-retention"


class Verification:
    """Collect named operations checks and fail at the first regression."""

    def __init__(self) -> None:
        self.passed: list[str] = []

    def check(self, name: str, condition: bool) -> None:
        """Record one passing check or raise a useful assertion."""
        if not condition:
            raise AssertionError(name)
        self.passed.append(name)
        print(f"PASS: {name}")


class ControlledSuccessfulRunner:
    """Hold one synthetic marketplace run open for lease-contention checks."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def run(self, url: str) -> MarketplaceRunResult:
        """Return safe deterministic metrics after the verifier releases the run."""
        del url
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return _run_result(Marketplace.GGSEL, PRIMARY_TENANT_ID)


class FailingRunner:
    """Raise private-looking data to prove runtime diagnostic sanitization."""

    def __init__(self) -> None:
        self.calls = 0

    async def run(self, url: str) -> object:
        """Fail without allowing the raw exception to cross the service boundary."""
        self.calls += 1
        raise RuntimeError(f"{PRIVATE_FAILURE}; source={url}")


class ImmediateSuccessfulRunner:
    """Return deterministic metrics for fresh-process restart verification."""

    def __init__(self, marketplace: Marketplace, tenant_id: UUID) -> None:
        self._marketplace = marketplace
        self._tenant_id = tenant_id

    async def run(self, url: str) -> MarketplaceRunResult:
        """Complete one verifier-owned run without any external I/O."""
        del url
        return _run_result(self._marketplace, self._tenant_id)


class RecordingAlertSink:
    """Capture safe lifecycle notifications without an external network sink."""

    def __init__(self) -> None:
        self.notifications: list[AlertLifecycleNotification] = []

    async def publish_lifecycle(
        self,
        notification: AlertLifecycleNotification,
    ) -> None:
        """Retain one notification for verifier assertions."""
        self.notifications.append(notification)


async def main() -> int:
    """Run the guarded production-shaped operations verification."""
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
    first_process: RuntimeProcess | None = None
    second_process: RuntimeProcess | None = None
    try:
        await _seed(scope_factory)
        controlled = ControlledSuccessfulRunner()
        failing = FailingRunner()
        first_process, first_components = _runtime(
            session_factory,
            owner_id="epic21-worker-a",
        )
        second_process, _ = _runtime(
            session_factory,
            owner_id="epic21-worker-b",
        )
        factories = {
            Marketplace.GGSEL.value: _constant_factory(controlled),
            Marketplace.PLAYEROK.value: _constant_factory(failing),
        }
        _register_polling(first_process, factories)
        _register_polling(second_process, factories)

        batch = await _verify_competing_workers(
            first_process,
            second_process,
            controlled,
            verifier,
        )
        verifier.check(
            "all marketplace calls stay inside verifier-owned runners",
            controlled.calls == 1 and failing.calls == 1,
        )
        await _verify_polling_persistence(scope_factory, batch, verifier)
        await _verify_transaction_rollback(scope_factory, verifier)
        await _verify_alert_lifecycle(first_components, batch, verifier)
        _verify_metrics(first_process, second_process, batch, verifier)
        await _verify_retention(first_process, scope_factory, verifier)
        await _verify_schema(engine, verifier)

        first_process.start()
        second_process.start()
        await asyncio.sleep(0)
        await first_process.stop()
        await second_process.stop()
        verifier.check("both worker runtimes stop gracefully", True)
        await _verify_released_leases(
            session_factory,
            verifier,
            context="worker shutdown",
        )
    finally:
        if first_process is not None:
            await first_process.stop()
        if second_process is not None:
            await second_process.stop()
        await engine.dispose()
        await default_engine.dispose()

    await _verify_fresh_process_restart(database_url, verifier)
    print()
    print(
        "EPIC 21 production operations PostgreSQL verification passed: "
        f"{len(verifier.passed)}/{len(verifier.passed)} checks."
    )
    return 0


def _runtime(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    owner_id: str,
) -> tuple[RuntimeProcess, RuntimeComponents]:
    settings = SchedulerSettings(
        tick_seconds=0.05,
        lease_enabled=True,
        owner_id=owner_id,
        lease_ttl_seconds=30.0,
    )
    components = create_postgres_runtime_components(
        settings,
        session_factory=session_factory,
    )
    return RuntimeProcess(components), components


def _register_polling(
    process: RuntimeProcess,
    factories: Mapping[str, MarketplaceIntegrationRunnerFactory],
) -> None:
    register_enabled_marketplace_integrations_job(
        process,
        runner_factories=factories,
        config=RuntimeJobConfig(
            interval_seconds=300,
            retry_count=1,
            retry_delay_seconds=0.01,
            timeout_seconds=5.0,
        ),
    )


def _constant_factory(
    runner: MarketplaceIntegrationRunner,
) -> MarketplaceIntegrationRunnerFactory:
    def factory(_integration: MarketplaceIntegration) -> MarketplaceIntegrationRunner:
        return runner

    return factory


async def _verify_competing_workers(
    first: RuntimeProcess,
    second: RuntimeProcess,
    controlled: ControlledSuccessfulRunner,
    verifier: Verification,
) -> MarketplaceIntegrationExecutionBatch:
    running = asyncio.create_task(first.execute_once(POLLING_JOB))
    await asyncio.wait_for(controlled.started.wait(), timeout=5.0)
    try:
        await second.execute_once(POLLING_JOB)
    finally:
        controlled.release.set()
        await running

    batch = _require_batch(first)
    first_statistics = first.list_statistics()[0]
    second_statistics = second.list_statistics()[0]
    verifier.check(
        "one worker owns the polling lease",
        first_statistics.successful_executions == 1,
    )
    verifier.check(
        "competing worker skips the active lease",
        second_statistics.lease_skips == 1 and second_statistics.total_executions == 0,
    )
    verifier.check(
        "polling batch selects every enabled primary-tenant integration",
        batch.selected_integrations == 3,
    )
    verifier.check(
        "polling batch isolates success failure and skipped outcomes",
        batch.executed_integrations == 2
        and batch.failed_integrations == 1
        and batch.skipped_integrations == 1,
    )
    verifier.check(
        "raw marketplace failures are sanitized",
        PRIVATE_FAILURE not in repr(batch)
        and "never-export"
        not in " ".join(
            execution.error_summary or "" for execution in batch.executions
        ),
    )
    verifier.check(
        "Scheduler succeeds despite one isolated integration failure",
        first.list_statuses()[0].state is JobExecutionState.SUCCEEDED,
    )
    return batch


async def _verify_polling_persistence(
    scope_factory: RepositoryScopeFactory,
    batch: MarketplaceIntegrationExecutionBatch,
    verifier: Verification,
) -> None:
    async with scope_factory() as repositories:
        success_runs = await repositories.marketplace_polling_runs.list_by_integration(
            PRIMARY_TENANT_ID,
            SUCCESS_INTEGRATION_ID,
            limit=100,
        )
        failure_runs = await repositories.marketplace_polling_runs.list_by_integration(
            PRIMARY_TENANT_ID,
            FAILURE_INTEGRATION_ID,
            limit=100,
        )
        skipped_runs = await repositories.marketplace_polling_runs.list_by_integration(
            PRIMARY_TENANT_ID,
            SKIPPED_INTEGRATION_ID,
            limit=100,
        )
        hidden = await repositories.marketplace_polling_runs.list_by_integration(
            FOREIGN_TENANT_ID,
            SUCCESS_INTEGRATION_ID,
            limit=100,
        )
        integrations = await repositories.marketplace_integrations.list_by_tenant(
            PRIMARY_TENANT_ID
        )

    verifier.check(
        "polling outcomes are durable",
        success_runs[0].status is MarketplacePollingRunStatus.SUCCEEDED
        and failure_runs[0].status is MarketplacePollingRunStatus.FAILED
        and skipped_runs[0].status is MarketplacePollingRunStatus.SKIPPED,
    )
    verifier.check(
        "polling metrics persist with the successful run",
        success_runs[0].offers_received == 7
        and success_runs[0].offers_persisted == 6
        and success_runs[0].processing_error_count == 0,
    )
    verifier.check(
        "persisted failure metadata remains sanitized",
        failure_runs[0].error_code == "RuntimeError"
        and failure_runs[0].error_summary == "Marketplace polling failed."
        and PRIVATE_FAILURE not in repr(failure_runs[0]),
    )
    verifier.check("tenant-scoped history cannot cross tenants", not hidden)
    by_id = {integration.id: integration for integration in integrations}
    verifier.check(
        "integration latest outcomes are committed atomically with history",
        by_id[SUCCESS_INTEGRATION_ID].last_successful_run_at is not None
        and by_id[FAILURE_INTEGRATION_ID].last_failed_run_at is not None
        and by_id[FAILURE_INTEGRATION_ID].last_error_code == "RuntimeError",
    )
    verifier.check(
        "batch evidence contains one durable polling ID per integration",
        all(execution.polling_run_id is not None for execution in batch.executions),
    )


async def _verify_transaction_rollback(
    scope_factory: RepositoryScopeFactory,
    verifier: Verification,
) -> None:
    before = await _history(scope_factory, PRIMARY_TENANT_ID, SUCCESS_INTEGRATION_ID)
    try:
        async with scope_factory() as repositories:
            await repositories.marketplace_polling_runs.save(
                MarketplacePollingRun(
                    id=ROLLBACK_RUN_ID,
                    tenant_id=PRIMARY_TENANT_ID,
                    integration_id=SUCCESS_INTEGRATION_ID,
                    marketplace=Marketplace.GGSEL.value,
                    status=MarketplacePollingRunStatus.SUCCEEDED,
                    started_at=datetime.now(UTC) - timedelta(seconds=1),
                    finished_at=datetime.now(UTC),
                )
            )
            raise RuntimeError("controlled rollback")
    except RuntimeError as error:
        if str(error) != "controlled rollback":
            raise
    else:
        raise AssertionError("controlled rollback must raise")

    after = await _history(scope_factory, PRIMARY_TENANT_ID, SUCCESS_INTEGRATION_ID)
    verifier.check(
        "polling transaction rolls back atomically",
        after == before and all(run.id != ROLLBACK_RUN_ID for run in after),
    )


async def _verify_alert_lifecycle(
    components: RuntimeComponents,
    batch: MarketplaceIntegrationExecutionBatch,
    verifier: Verification,
) -> None:
    read_scope = components.read_repository_scope_factory
    if read_scope is None:
        raise RuntimeError("PostgreSQL runtime is missing its read scope.")
    sink = RecordingAlertSink()
    monitor = RuntimeAlertMonitor(
        read_repository_scope_factory=read_scope,
        lifecycle=OperationalAlertLifecycle(),
        sink=sink,
        dashboard_window=timedelta(hours=24),
    )
    observed_at = datetime.now(UTC)
    opened = await monitor.evaluate(batch=batch, observed_at=observed_at)
    repeated = await monitor.evaluate(
        batch=batch,
        observed_at=observed_at + timedelta(minutes=1),
    )
    resolved = await monitor.evaluate(
        batch=None,
        observed_at=observed_at + timedelta(minutes=2),
    )

    verifier.check(
        "runtime alert monitor reads the tenant dashboard",
        opened.dashboard_tenants == 1 and opened.dashboard_error_code is None,
    )
    verifier.check(
        "failed and skipped polling open lifecycle alerts",
        opened.active_alerts == 2
        and opened.notifications == 2
        and opened.delivered == 2,
    )
    verifier.check(
        "duplicate alerts are suppressed inside the reminder window",
        repeated.notifications == 0 and repeated.suppressed == 2,
    )
    verifier.check(
        "cleared conditions emit resolved notifications",
        resolved.active_alerts == 0
        and resolved.notifications == 2
        and len(sink.notifications) == 4,
    )
    verifier.check(
        "alert lifecycle output excludes source and exception secrets",
        PRIVATE_FAILURE not in repr(sink.notifications)
        and PRIVATE_SOURCE_URL not in repr(sink.notifications),
    )


def _verify_metrics(
    first: RuntimeProcess,
    second: RuntimeProcess,
    batch: MarketplaceIntegrationExecutionBatch,
    verifier: Verification,
) -> None:
    exporter = RuntimeMetricsExporter()
    first_payload = exporter.render(first, batch)
    second_payload = exporter.render(second)
    with TemporaryDirectory(prefix="mediaengine-epic21-") as directory:
        first_path = Path(directory) / "worker-a.prom"
        second_path = Path(directory) / "worker-b.prom"
        PrometheusTextfileWriter(first_path).write(first_payload)
        PrometheusTextfileWriter(second_path).write(second_payload)
        first_file = first_path.read_text(encoding="utf-8")
        second_file = second_path.read_text(encoding="utf-8")

    verifier.check(
        "each worker exports an independent metrics file",
        first_path != second_path
        and first_file == first_payload
        and second_file == second_payload,
    )
    verifier.check(
        "metrics report marketplace outcomes and Scheduler success",
        'marketplace="ggsel",outcome="succeeded"} 1' in first_payload
        and 'marketplace="playerok",outcome="failed"} 1' in first_payload
        and 'marketplace="funpay",outcome="skipped"} 1' in first_payload
        and "mediaengine_scheduler_job_successes_total" in first_payload,
    )
    verifier.check(
        "competing worker exports its lease skip",
        (
            "mediaengine_scheduler_job_lease_skips_total"
            '{job="enabled-marketplace-integrations"} 1'
        )
        in second_payload,
    )
    verifier.check(
        "metrics exclude source URLs credentials and tenant identifiers",
        PRIVATE_SOURCE_URL not in first_payload
        and PRIVATE_FAILURE not in first_payload
        and str(PRIMARY_TENANT_ID) not in first_payload,
    )


async def _verify_retention(
    process: RuntimeProcess,
    scope_factory: RepositoryScopeFactory,
    verifier: Verification,
) -> None:
    register_marketplace_polling_retention_job(
        process,
        retain_for_seconds=30 * 24 * 60 * 60,
        keep_latest_per_integration=1,
        batch_size=100,
        config=RuntimeJobConfig(
            interval_seconds=24 * 60 * 60,
            retry_count=1,
            retry_delay_seconds=0.01,
            timeout_seconds=5.0,
        ),
    )
    await process.execute_once(RETENTION_JOB)
    result = process.get_last_result(RETENTION_JOB)
    if not isinstance(result, MarketplacePollingRetentionBatch):
        raise RuntimeError("Retention Scheduler job returned an invalid result.")

    success = await _history(
        scope_factory,
        PRIMARY_TENANT_ID,
        SUCCESS_INTEGRATION_ID,
    )
    foreign = await _history(
        scope_factory,
        FOREIGN_TENANT_ID,
        FOREIGN_INTEGRATION_ID,
    )
    verifier.check(
        "scheduled retention discovers every tenant with polling history",
        result.tenant_count == 2,
    )
    verifier.check(
        "scheduled retention deletes deterministic expired history",
        result.deleted_count == 5 and not result.batch_limit_reached,
    )
    verifier.check(
        "retention preserves the newest primary-tenant run",
        len(success) == 1
        and success[0].status is MarketplacePollingRunStatus.SUCCEEDED,
    )
    verifier.check(
        "retention preserves the newest foreign-tenant evidence independently",
        len(foreign) == 1 and foreign[0].id == _historical_run_id(FOREIGN_TENANT_ID, 3),
    )
    verifier.check(
        "retention completes through Scheduler",
        process.list_statuses()[1].state is JobExecutionState.SUCCEEDED,
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
                        "WHERE schemaname = 'public' "
                        "AND tablename = 'marketplace_polling_runs'"
                    )
                )
            ).scalars()
        )
    verifier.check("current Alembic head is applied", revision == _migration_head())
    verifier.check(
        "polling-history indexes support operations reads and retention",
        {
            "ix_marketplace_polling_runs_integration_finished",
            "ix_marketplace_polling_runs_status_finished",
        }
        <= indexes,
    )


async def _verify_released_leases(
    session_factory: async_sessionmaker[AsyncSession],
    verifier: Verification,
    *,
    context: str,
) -> None:
    repository = PostgresSchedulerLeaseRepository(session_factory)
    verifier.check(
        f"{context} leaves no polling lease",
        await repository.get(POLLING_JOB) is None,
    )
    verifier.check(
        f"{context} leaves no retention lease",
        await repository.get(RETENTION_JOB) is None,
    )


async def _verify_fresh_process_restart(
    database_url: str,
    verifier: Verification,
) -> None:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    scope_factory = create_postgres_repository_scope(session_factory)
    process, _ = _runtime(session_factory, owner_id="epic21-worker-restarted")
    factories = {
        Marketplace.GGSEL.value: _restart_factory,
        Marketplace.PLAYEROK.value: _restart_factory,
    }
    _register_polling(process, factories)
    try:
        before = await _history(
            scope_factory,
            PRIMARY_TENANT_ID,
            SUCCESS_INTEGRATION_ID,
        )
        await process.execute_once(POLLING_JOB)
        batch = _require_batch(process)
        after = await _history(
            scope_factory,
            PRIMARY_TENANT_ID,
            SUCCESS_INTEGRATION_ID,
        )
        foreign = await _history(
            scope_factory,
            FOREIGN_TENANT_ID,
            FOREIGN_INTEGRATION_ID,
        )
        verifier.check(
            "fresh engine reads retained PostgreSQL history",
            len(before) == 1 and len(foreign) == 1,
        )
        verifier.check(
            "fresh worker process executes after restart",
            batch.selected_integrations == 3
            and batch.failed_integrations == 0
            and process.list_statuses()[0].state is JobExecutionState.SUCCEEDED,
        )
        verifier.check(
            "fresh worker appends durable history without losing retained evidence",
            len(after) == 2 and before[0] in after,
        )
        await _verify_released_leases(
            session_factory,
            verifier,
            context="fresh worker execution",
        )
    finally:
        await process.stop()
        await engine.dispose()


def _restart_factory(
    integration: MarketplaceIntegration,
) -> MarketplaceIntegrationRunner:
    return ImmediateSuccessfulRunner(
        Marketplace(integration.marketplace),
        integration.tenant_id,
    )


def _require_batch(process: RuntimeProcess) -> MarketplaceIntegrationExecutionBatch:
    result = process.get_last_result(POLLING_JOB)
    if not isinstance(result, MarketplaceIntegrationExecutionBatch):
        raise RuntimeError("Polling Scheduler job returned an invalid result.")
    return result


async def _seed(scope_factory: RepositoryScopeFactory) -> None:
    async with scope_factory() as repositories:
        await repositories.tenants.create(
            Tenant(
                id=PRIMARY_TENANT_ID,
                name="EPIC 21 Operations Primary",
                slug="epic21-operations-primary",
                created_at=CREATED_AT,
                updated_at=CREATED_AT,
            )
        )
        await repositories.tenants.create(
            Tenant(
                id=FOREIGN_TENANT_ID,
                name="EPIC 21 Operations Foreign",
                slug="epic21-operations-foreign",
                created_at=CREATED_AT,
                updated_at=CREATED_AT,
            )
        )
        for integration in (
            _integration(
                SUCCESS_INTEGRATION_ID,
                PRIMARY_TENANT_ID,
                Marketplace.GGSEL.value,
                PRIVATE_SOURCE_URL,
            ),
            _integration(
                FAILURE_INTEGRATION_ID,
                PRIMARY_TENANT_ID,
                Marketplace.PLAYEROK.value,
                "https://source.invalid/failure",
            ),
            _integration(
                SKIPPED_INTEGRATION_ID,
                PRIMARY_TENANT_ID,
                Marketplace.FUNPAY.value,
                None,
            ),
            _integration(
                FOREIGN_INTEGRATION_ID,
                FOREIGN_TENANT_ID,
                Marketplace.GGSEL.value,
                "https://source.invalid/foreign",
                enabled=False,
            ),
        ):
            await repositories.marketplace_integrations.save(integration)

        for number in range(1, 4):
            await repositories.marketplace_polling_runs.save(
                _historical_run(
                    PRIMARY_TENANT_ID,
                    SUCCESS_INTEGRATION_ID,
                    number,
                )
            )
            await repositories.marketplace_polling_runs.save(
                _historical_run(
                    FOREIGN_TENANT_ID,
                    FOREIGN_INTEGRATION_ID,
                    number,
                )
            )


def _integration(
    integration_id: UUID,
    tenant_id: UUID,
    marketplace: str,
    source_url: str | None,
    *,
    enabled: bool = True,
) -> MarketplaceIntegration:
    return MarketplaceIntegration(
        id=integration_id,
        tenant_id=tenant_id,
        marketplace=marketplace,
        display_name=f"{marketplace} operations verification",
        source_url=source_url,
        enabled=enabled,
        status=(
            MarketplaceIntegrationStatus.ACTIVE
            if enabled
            else MarketplaceIntegrationStatus.DISABLED
        ),
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )


def _historical_run(
    tenant_id: UUID,
    integration_id: UUID,
    number: int,
) -> MarketplacePollingRun:
    finished_at = CREATED_AT + timedelta(days=number)
    return MarketplacePollingRun(
        id=_historical_run_id(tenant_id, number),
        tenant_id=tenant_id,
        integration_id=integration_id,
        marketplace=Marketplace.GGSEL.value,
        status=MarketplacePollingRunStatus.SUCCEEDED,
        started_at=finished_at - timedelta(seconds=2),
        finished_at=finished_at,
        offers_received=3,
        offers_persisted=3,
    )


def _historical_run_id(tenant_id: UUID, number: int) -> UUID:
    tenant_offset = 0 if tenant_id == PRIMARY_TENANT_ID else 100
    return UUID(int=57_000 + tenant_offset + number)


def _run_result(
    marketplace: Marketplace,
    tenant_id: UUID,
) -> MarketplaceRunResult:
    return MarketplaceRunResult(
        marketplace=marketplace,
        offers_received=7,
        offers_persisted=6,
        comparison_results=2,
        snapshots_created=6,
        snapshots_persisted=6,
        skipped_offers=1,
        price_changes_detected=2,
        event_candidates_built=2,
        events_created=1,
        events_existing=1,
        skipped_event_candidates=0,
        event_ids=(),
        events_scored=0,
        content_items_generated=0,
        persistence_committed=True,
        errors=(),
        tenant_id=tenant_id,
    )


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
    head = ScriptDirectory.from_config(_alembic_config()).get_current_head()
    if head is None:
        raise RuntimeError("Alembic has no current head revision.")
    return head


def _alembic_config(database_url: str | None = None) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    if database_url is not None:
        config.set_main_option("sqlalchemy.url", database_url)
    return config


def _require_isolated_database(database_url: str) -> None:
    url = make_url(database_url)
    database = url.database or ""
    if not database.startswith("epic21_operations_"):
        raise RuntimeError(
            f"{DATABASE_URL_ENV} must target an epic21_operations_* database."
        )
    if url.host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("EPIC 21 verification requires local PostgreSQL.")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
