"""Verify EPIC 17 Scheduler integration selection against PostgreSQL."""

# ruff: noqa: E402, I001
from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
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

from app.database.repository_scope import create_postgres_repository_scope
from app.domain.marketplace_integrations import (
    MarketplaceIntegration,
    MarketplaceIntegrationStatus,
)
from app.domain.tenancy import Tenant
from app.repositories.provider import create_postgres_provider
from app.scheduler.jobs import EnabledMarketplaceIntegrationsJob, JobExecutionState
from app.services.marketplace_integration_execution import (
    MarketplaceIntegrationExecutionService,
)

DATABASE_URL_ENV = "EPIC17_DATABASE_URL"
TENANT_A_ID = UUID("10000000-0000-4000-8000-000000000201")
TENANT_B_ID = UUID("10000000-0000-4000-8000-000000000202")
NOW = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)


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


@dataclass(slots=True)
class RunnerCall:
    """Captured execution delegated by integration selection."""

    tenant_id: UUID
    integration_id: UUID
    marketplace: str
    source_url: str


class RecordingRunner:
    """Runner double that records selected integration context."""

    def __init__(
        self,
        integration: MarketplaceIntegration,
        calls: list[RunnerCall],
    ) -> None:
        self._integration = integration
        self._calls = calls

    async def run(self, url: str) -> str:
        """Record one marketplace application runner invocation."""
        self._calls.append(
            RunnerCall(
                tenant_id=self._integration.tenant_id,
                integration_id=self._integration.id,
                marketplace=self._integration.marketplace,
                source_url=url,
            )
        )
        return f"ran:{self._integration.marketplace}:{url}"


async def main() -> int:
    """Run EPIC 17 Scheduler integration selection verification."""
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
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with session.begin():
                await _seed_data(session)

        await _verify_selection(session_factory, verifier)
        await _verify_scheduler_job(session_factory, verifier)
        await _verify_fresh_session_selection(session_factory, verifier)
    finally:
        await engine.dispose()

    print(
        "EPIC 17 Scheduler integration selection PostgreSQL verification: "
        f"{len(verifier.passed)} checks passed."
    )
    return 0


async def _seed_data(session: AsyncSession) -> None:
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
            is_active=False,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    for integration in (
        _integration(number=1, marketplace="ggsel"),
        _integration(
            number=2,
            marketplace="playerok",
            source_url="https://playerok.com/products",
        ),
        _integration(
            number=3,
            enabled=False,
            source_url="https://ggsel.net/catalog/disabled-flag",
        ),
        _integration(
            number=4,
            status=MarketplaceIntegrationStatus.DISABLED,
            source_url="https://ggsel.net/catalog/disabled-status",
        ),
        _integration(
            number=5,
            tenant_id=TENANT_B_ID,
            source_url="https://ggsel.net/catalog/inactive-tenant",
        ),
        _integration(number=6, source_url=None),
        _integration(
            number=7,
            marketplace="future-market",
            source_url="https://example.com/future",
        ),
    ):
        await repositories.marketplace_integrations.save(integration)


async def _verify_selection(
    session_factory: async_sessionmaker[AsyncSession],
    verifier: Verification,
) -> None:
    calls: list[RunnerCall] = []
    service = _service(session_factory, calls)
    batch = await service.run_enabled_integrations()

    verifier.check(
        "active enabled integrations are selected", batch.selected_integrations == 4
    )
    verifier.check(
        "supported integrations are executed", batch.executed_integrations == 2
    )
    verifier.check(
        "unsupported or incomplete integrations are skipped",
        batch.skipped_integrations == 2,
    )
    verifier.check(
        "runner receives tenant and integration context",
        calls
        == [
            RunnerCall(
                tenant_id=TENANT_A_ID,
                integration_id=UUID(int=19_001),
                marketplace="ggsel",
                source_url="https://ggsel.net/catalog/minecraft",
            ),
            RunnerCall(
                tenant_id=TENANT_A_ID,
                integration_id=UUID(int=19_002),
                marketplace="playerok",
                source_url="https://playerok.com/products",
            ),
        ],
    )
    verifier.check(
        "skipped reasons are deterministic",
        [execution.skipped_reason for execution in batch.executions[2:]]
        == ["missing_source_url", "unsupported_marketplace"],
    )


async def _verify_scheduler_job(
    session_factory: async_sessionmaker[AsyncSession],
    verifier: Verification,
) -> None:
    calls: list[RunnerCall] = []
    job = EnabledMarketplaceIntegrationsJob(_service(session_factory, calls))

    await job.execute()

    verifier.check("Scheduler job delegates to integration selection", len(calls) == 2)
    verifier.check(
        "Scheduler job reports success",
        job.status.state is JobExecutionState.SUCCEEDED,
    )


async def _verify_fresh_session_selection(
    session_factory: async_sessionmaker[AsyncSession],
    verifier: Verification,
) -> None:
    calls: list[RunnerCall] = []
    batch = await _service(session_factory, calls).run_enabled_integrations()

    async with session_factory() as session:
        repositories = create_postgres_provider(session)
        all_enabled = await repositories.marketplace_integrations.list_enabled()

    verifier.check("fresh-session selected integrations persist", len(all_enabled) == 5)
    verifier.check(
        "fresh-session inactive tenant remains excluded",
        batch.selected_integrations == 4,
    )
    verifier.check("fresh-session execution remains deterministic", len(calls) == 2)


def _service(
    session_factory: async_sessionmaker[AsyncSession],
    calls: list[RunnerCall],
) -> MarketplaceIntegrationExecutionService:
    return MarketplaceIntegrationExecutionService(
        repository_scope_factory=create_postgres_repository_scope(session_factory),
        runner_factories={
            "ggsel": lambda integration: RecordingRunner(integration, calls),
            "playerok": lambda integration: RecordingRunner(integration, calls),
        },
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
    tenant_id: UUID = TENANT_A_ID,
    marketplace: str = "ggsel",
    source_url: str | None = "https://ggsel.net/catalog/minecraft",
    enabled: bool = True,
    status: MarketplaceIntegrationStatus = MarketplaceIntegrationStatus.ACTIVE,
) -> MarketplaceIntegration:
    timestamp = NOW + timedelta(minutes=number)
    return MarketplaceIntegration(
        id=UUID(int=19_000 + number),
        tenant_id=tenant_id,
        marketplace=marketplace,
        display_name=f"{marketplace} {number}",
        enabled=enabled,
        status=status,
        source_url=source_url,
        created_at=timestamp,
        updated_at=timestamp,
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
