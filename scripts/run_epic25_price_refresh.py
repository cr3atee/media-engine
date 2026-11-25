"""Run the bounded local six-offer price refresh through existing runtime services."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import asyncio
import math
import os
import sys
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config.settings import SchedulerSettings
from app.database.session import engine as default_engine
from app.domain.marketplace import Marketplace
from app.domain.marketplace_integrations import (
    MarketplaceIntegration,
    MarketplaceIntegrationStatus,
)
from app.runtime.bootstrap import create_postgres_runtime_components
from app.runtime.curated_prices import PollingHttpClient, ingest_curated_category
from app.runtime.marketplaces import create_marketplace_processing_pipeline
from app.runtime.process import RuntimeJobConfig, RuntimeProcess
from app.scheduler.jobs import EnabledMarketplaceIntegrationsJob
from app.services.marketplace_application_runner import MarketplaceApplicationRunner
from app.services.marketplace_ingestion import MarketplaceIngestionResult
from app.services.marketplace_integration_execution import (
    MarketplaceIntegrationExecutionService,
)
from app.services.repository_scope import RepositoryScopeFactory
from scripts.run_catalog_review_postgres import TENANT_ID, _require_isolated_database
from scripts.run_mediaengine_worker import (
    _install_termination_handler,
    _print_marketplace_result,
    _print_statuses,
    _wait_for_shutdown,
)

DATABASE_ENV = "EPIC25_PRICE_REFRESH_DATABASE_URL"
LIVE_ENV = "EPIC25_PRICE_REFRESH_LIVE"
LIVE_GUARD = "I_UNDERSTAND_THIS_UPDATES_APPROVED_LOCAL_PRICES"
APPROVED_OFFERS = {
    ("ggsel", "5077855"): UUID("dc7a6323-d5fc-5675-a2ff-0fe6ab4a70d1"),
    ("funpay", "19847269"): UUID("dc7a6323-d5fc-5675-a2ff-0fe6ab4a70d1"),
    ("ggsel", "103585387"): UUID("9c0f59b4-7479-5034-9c21-f7a4e6d86967"),
    ("funpay", "82381719"): UUID("9c0f59b4-7479-5034-9c21-f7a4e6d86967"),
    ("ggsel", "102361507"): UUID("b7936dd8-1bd9-5073-ab02-59b381dfec9a"),
    ("funpay", "79355854"): UUID("b7936dd8-1bd9-5073-ab02-59b381dfec9a"),
}


def require_local_catalog(url: str) -> None:
    """Refuse production URLs and the separate human-review database."""
    _require_isolated_database(url)
    database = make_url(url).database or ""
    if database != "epic23_catalog_review_epic25_local_catalog" and not (
        database.startswith("epic23_catalog_review_epic25_price_refresh_")
    ):
        raise ValueError(
            "Only the local catalog or a price-refresh test DB is allowed."
        )


def _interval(value: str) -> int:
    result = int(value)
    if result < 1800:
        raise argparse.ArgumentTypeError("Price refresh interval must be >= 1800.")
    return result


def _duration(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("Duration must be positive and finite.")
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse an explicit read-only check, one live batch or periodic execution."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Read-only scope preflight.")
    mode.add_argument(
        "--once", action="store_true", help="Run one live batch and exit."
    )
    parser.add_argument("--interval-seconds", type=_interval, default=1800)
    parser.add_argument("--duration-seconds", type=_duration)
    parser.add_argument("--stop-file", type=Path)
    parser.add_argument(
        "--defer-first-run",
        action="store_true",
        help="Schedule the first refresh after the interval, not immediately.",
    )
    arguments = parser.parse_args(argv)
    if arguments.once and arguments.defer_first_run:
        parser.error("--once cannot be combined with --defer-first-run")
    return arguments


async def load_refresh_targets(
    scope: RepositoryScopeFactory,
) -> dict[UUID, dict[str, UUID]]:
    """Require the exact retained six links and their existing source mappings."""
    async with scope() as repos:
        offers = await repos.offers.list_by_tenant(TENANT_ID)
        products = await repos.canonical_products.list_by_tenant(TENANT_ID)
        if {p.id for p in products} != set(APPROVED_OFFERS.values()) or {
            (o.marketplace, o.external_id) for o in offers
        } != set(APPROVED_OFFERS):
            raise ValueError(
                "Local catalog differs from the approved three-product scope."
            )
        targets: dict[UUID, dict[str, UUID]] = {}
        rules = await repos.catalog_source_rules.list_by_tenant(TENANT_ID)
        rule_index = {rule.id: rule for rule in rules}
        for offer in offers:
            assert offer.external_id is not None
            product_id = APPROVED_OFFERS[(offer.marketplace, offer.external_id)]
            rule = (
                rule_index.get(offer.catalog_source_rule_id)
                if offer.catalog_source_rule_id is not None
                else None
            )
            if rule is None or offer.canonical_product_id != product_id:
                raise ValueError("An approved link or its source rule changed.")
            integration = await repos.marketplace_integrations.get_by_tenant_and_id(
                TENANT_ID, rule.integration_id
            )
            if (
                integration is None
                or not integration.enabled
                or integration.status is not MarketplaceIntegrationStatus.ACTIVE
                or integration.marketplace != offer.marketplace
                or integration.source_url is None
                or rule.source_category_id != offer.source_category_id
                or rule.hub_code != offer.catalog_hub_code
                or rule.section_code != offer.catalog_section_code
            ):
                raise ValueError("An approved source integration changed.")
            targets.setdefault(integration.id, {})[offer.external_id] = product_id
        if len(targets) != 6:
            raise ValueError("Expected six separate curated source integrations.")
        return targets


async def _watch_stop_file(path: Path, event: asyncio.Event) -> None:
    while not path.exists():
        await asyncio.sleep(1)
    event.set()


async def run(arguments: argparse.Namespace, url: str) -> int:
    """Compose only existing polling, processing, repository and Scheduler layers."""
    require_local_catalog(url)
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    components = create_postgres_runtime_components(
        SchedulerSettings(lease_enabled=True, owner_id=""), session_factory=factory
    )
    process = RuntimeProcess(components)
    scheduler_stopped = False
    shutdown = asyncio.Event()
    remove_handler = _install_termination_handler(shutdown)
    stop_task: asyncio.Task[None] | None = None
    try:
        targets = await load_refresh_targets(components.repository_scope_factory)
        if arguments.check:
            print(
                "PASS read-only preflight: three products, six reviewed offers/sources."
            )
            return 0
        if os.getenv(LIVE_ENV) != LIVE_GUARD:
            raise ValueError("Explicit live price-refresh guard is required.")
        if arguments.stop_file is not None:
            if arguments.stop_file.exists():
                print("STOP: control file already exists; no polling performed.")
                return 0
            stop_task = asyncio.create_task(
                _watch_stop_file(arguments.stop_file, shutdown)
            )
        async with PollingHttpClient(
            cooldown_seconds=arguments.interval_seconds
        ) as http:
            pipeline = create_marketplace_processing_pipeline(http)

            def make_runner(
                integration: MarketplaceIntegration,
            ) -> MarketplaceApplicationRunner:
                async def ingest(source_url: str) -> MarketplaceIngestionResult:
                    return await ingest_curated_category(
                        http, integration.marketplace, source_url
                    )

                return MarketplaceApplicationRunner(
                    marketplace=Marketplace(integration.marketplace),
                    ingestion=ingest,
                    repository_scope_factory=components.repository_scope_factory,
                    pipeline=pipeline,
                    tenant_id=TENANT_ID,
                    integration_id=integration.id,
                    price_refresh_targets=targets[integration.id],
                )

            service = MarketplaceIntegrationExecutionService(
                repository_scope_factory=components.repository_scope_factory,
                runner_factories={"ggsel": make_runner, "funpay": make_runner},
                integration_ids=frozenset(targets),
            )
            job = EnabledMarketplaceIntegrationsJob(service)
            process.register_job(
                job,
                RuntimeJobConfig(
                    enabled=not arguments.once,
                    interval_seconds=None
                    if arguments.once
                    else arguments.interval_seconds,
                    retry_count=0,
                    timeout_seconds=300,
                ),
            )
            if not arguments.defer_first_run:
                await process.execute_once(job.name)
            _print_marketplace_result(process, job.name)
            _print_statuses(process)
            if arguments.once:
                result = job.last_result
                return (
                    0 if result is not None and service_result_succeeded(result) else 1
                )
            print(f"Periodic refresh: {arguments.interval_seconds}s; no AI/Telegram.")
            process.start()
            for schedule in process.list_schedule_statuses():
                print(f"Next scheduled run (UTC): {schedule.next_scheduled_run}")
            try:
                await _wait_for_shutdown(
                    shutdown, duration_seconds=arguments.duration_seconds
                )
            finally:
                await process.stop()
                scheduler_stopped = True
        return 0
    finally:
        if not scheduler_stopped:
            await process.stop()
        if stop_task is not None:
            stop_task.cancel()
            with suppress(asyncio.CancelledError):
                await stop_task
        remove_handler()
        await engine.dispose()
        await default_engine.dispose()


def service_result_succeeded(result: object) -> bool:
    """Keep partial-source failures visible in one-shot verification exit status."""
    from app.services.marketplace_integration_execution import (
        MarketplaceIntegrationExecutionBatch,
    )

    return (
        isinstance(result, MarketplaceIntegrationExecutionBatch)
        and result.selected_integrations == 6
        and result.failed_integrations == 0
        and result.executed_integrations == 6
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Validate local configuration; never print credentials or raw source errors."""
    arguments = parse_args(argv)
    url = os.getenv(DATABASE_ENV, "")
    try:
        return asyncio.run(run(arguments, url))
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        print(
            f"Price refresh stopped: {type(error).__name__}; check local configuration."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
