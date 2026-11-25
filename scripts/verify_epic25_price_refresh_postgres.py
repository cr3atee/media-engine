"""Exercise synthetic refresh cases only on a restored, isolated catalog copy."""

# ruff: noqa: E402
from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config.settings import SchedulerSettings
from app.core.http_client import HttpClient
from app.database.public_read_scope import create_postgres_public_read_repository_scope
from app.database.repository_scope import create_postgres_repository_scope
from app.database.session import engine as default_engine
from app.domain.activation_conditions import (
    AccountRequirement,
    ActivationConditions,
    DeliveryMethod,
)
from app.domain.marketplace import Marketplace
from app.domain.marketplace_integrations import MarketplaceIntegration
from app.parsers.models import ParsedOffer
from app.repositories.provider import RepositoryProvider, create_postgres_provider
from app.runtime.bootstrap import create_postgres_runtime_components
from app.runtime.marketplaces import create_marketplace_processing_pipeline
from app.runtime.process import RuntimeJobConfig, RuntimeProcess
from app.scheduler.jobs import EnabledMarketplaceIntegrationsJob
from app.services.marketplace_application_runner import (
    MarketplaceApplicationRunner,
    MarketplaceRunResult,
    PriceRefreshScopeError,
)
from app.services.marketplace_integration_execution import (
    MarketplaceIntegrationExecutionBatch,
    MarketplaceIntegrationExecutionService,
)
from app.services.repository_scope import RepositoryScopeFactory
from scripts.run_catalog_review_postgres import TENANT_ID
from scripts.run_epic25_price_refresh import (
    APPROVED_OFFERS,
    load_refresh_targets,
    require_local_catalog,
)

DATABASE_ENV = "EPIC25_PRICE_REFRESH_TEST_DATABASE_URL"


async def verify(url: str) -> int:
    """Never fetch live sources; deliberately modify prices in this test DB only."""
    require_local_catalog(url)
    from sqlalchemy.engine import make_url

    if not (make_url(url).database or "").startswith(
        "epic23_catalog_review_epic25_price_refresh_verify_"
    ):
        raise ValueError("Verifier requires a disposable restored verification DB.")
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    scope = create_postgres_repository_scope(factory)
    checks: list[str] = []
    pending_workers: list[asyncio.Task[MarketplaceRunResult]] = []

    def check(name: str, condition: bool) -> None:
        if not condition:
            raise AssertionError(name)
        checks.append(name)
        print(f"PASS {name}")

    try:
        targets = await load_refresh_targets(scope)
        async with scope() as repos:
            original = tuple(await repos.offers.list_by_tenant(TENANT_ID))
            integrations = {
                i.id: i
                for i in await repos.marketplace_integrations.list_by_tenant(TENANT_ID)
                if i.id in targets
            }
        check("restored catalog contains six scoped offers", len(original) == 6)
        async with engine.connect() as conn:
            immutable_before: dict[str, dict[str, str]] = {
                table: {
                    str(row[0]): str(row[1])
                    for row in (
                        await conn.execute(
                            text(
                                "SELECT id::text,md5(row_to_json(t)::text) "
                                f"FROM {table} t ORDER BY id"
                            )
                        )
                    ).all()
                }
                for table in (
                    "canonical_products",
                    "canonical_offer_decisions",
                    "admin_actions",
                )
            }

        async with HttpClient() as http:
            pipeline = create_marketplace_processing_pipeline(http)

            def make_runner(
                integration: MarketplaceIntegration,
                offers: Sequence[ParsedOffer],
                selected_scope: RepositoryScopeFactory = scope,
                arrived: asyncio.Event | None = None,
            ) -> MarketplaceApplicationRunner:
                transaction_open = ContextVar("refresh_transaction_open", default=False)

                @asynccontextmanager
                async def tracked_scope() -> AsyncIterator[RepositoryProvider]:
                    token = transaction_open.set(True)
                    try:
                        async with selected_scope() as provider:
                            yield provider
                    finally:
                        transaction_open.reset(token)

                async def ingest(source_url: str) -> Sequence[ParsedOffer]:
                    check(
                        "ingestion outside DB transaction",
                        not transaction_open.get(),
                    )
                    if arrived is not None:
                        arrived.set()
                    return offers

                return MarketplaceApplicationRunner(
                    marketplace=Marketplace(integration.marketplace),
                    ingestion=ingest,
                    repository_scope_factory=tracked_scope,
                    pipeline=pipeline,
                    tenant_id=TENANT_ID,
                    integration_id=integration.id,
                    price_refresh_targets=targets[integration.id],
                )

            def integration_for(offer: ParsedOffer) -> MarketplaceIntegration:
                return next(
                    i
                    for i in integrations.values()
                    if offer.external_id in targets[i.id]
                    and offer.marketplace == i.marketplace
                )

            for offer in original:
                assert offer.price is not None
                integration = integration_for(offer)
                fresh = replace(
                    offer,
                    price=offer.price + 1,
                    canonical_product_id=None,
                    activation_conditions=None,
                )
                result = await make_runner(
                    integration, (fresh, replace(fresh, external_id="offline-extra"))
                ).run(integration.source_url or "")
                async with scope() as repos:
                    stored = await repos.offers.get_by_identity(
                        TENANT_ID, offer.marketplace, offer.external_id or ""
                    )
                check(
                    "only observed price changed",
                    stored == replace(offer, price=offer.price + 1),
                )
                check("unapproved offers not persisted", result.offers_persisted == 1)
                check(
                    "history observed without deactivation",
                    result.snapshots_persisted == 1 and result.offers_deactivated == 0,
                )

            target = original[0]
            integration = integration_for(target)
            assert target.external_id is not None and target.price is not None

            async def read_target() -> ParsedOffer:
                async with scope() as repos:
                    row = await repos.offers.get_by_identity(
                        TENANT_ID, target.marketplace, target.external_id or ""
                    )
                    assert row is not None
                    return row

            async def history_size() -> int:
                async with scope() as repos:
                    return len(
                        await repos.price_history.get_history(
                            TENANT_ID, target.marketplace, target.external_id or ""
                        )
                    )

            baseline = await read_target()
            history_before = await history_size()
            invalid_batches = (
                (),
                (replace(target, price=Decimal("0")),),
                (replace(target, currency="USD"),),
                (replace(target, title="Offline changed product"),),
                (target, target),
            )
            for incoming in invalid_batches:
                try:
                    await make_runner(integration, incoming).run(
                        integration.source_url or ""
                    )
                except PriceRefreshScopeError:
                    pass
                else:
                    raise AssertionError("Invalid source response accepted")
                check(
                    "invalid/missing quote retains price and history",
                    await read_target() == baseline
                    and await history_size() == history_before,
                )

            @asynccontextmanager
            async def rollback_scope() -> AsyncIterator[RepositoryProvider]:
                async with scope() as repos:
                    yield repos
                    raise RuntimeError("Offline injected rollback")

            try:
                await make_runner(
                    integration,
                    (replace(target, price=target.price + 2),),
                    rollback_scope,
                ).run(integration.source_url or "")
            except RuntimeError as error:
                assert str(error) == "Offline injected rollback"
            check(
                "quote/history/observation transaction rolls back",
                await read_target() == baseline
                and await history_size() == history_before,
            )

            conditions = ActivationConditions(
                regions=("RU",),
                excluded_regions=(),
                device="pc",
                plan="offline_plan",
                period="P1M",
                delivery_method=DeliveryMethod.KEY,
                account_requirement=AccountRequirement.EXISTING_ONLY,
                vpn_required=False,
                activation_window_seconds=None,
            )
            arrived = asyncio.Event()
            async with scope() as repos:
                locked = await repos.offers.get_by_identity_for_update(
                    TENANT_ID, target.marketplace, target.external_id
                )
                assert locked is not None
                assert await repos.offers.compare_and_set_activation_conditions(
                    TENANT_ID, locked, conditions
                )
                task = asyncio.create_task(
                    make_runner(
                        integration,
                        (replace(target, price=target.price + 3),),
                        arrived=arrived,
                    ).run(integration.source_url or "")
                )
                pending_workers.append(task)
                await asyncio.wait_for(arrived.wait(), timeout=5)
                await asyncio.sleep(0.1)
                check("refresh waits for concurrent reviewer row lock", not task.done())
            await asyncio.wait_for(task, timeout=10)
            current = await read_target()
            check(
                "concurrent reviewed conditions preserved",
                current.activation_conditions == conditions,
            )

            arrived = asyncio.Event()
            history_before = await history_size()
            async with factory.begin() as admin_session:
                repos = create_postgres_provider(admin_session)
                await repos.offers.get_by_identity_for_update(
                    TENANT_ID, target.marketplace, target.external_id
                )
                # Simulate a concurrent administrative unlink in this test DB only.
                await admin_session.execute(
                    text(
                        "UPDATE offers SET canonical_product_id=NULL "
                        "WHERE tenant_id=:tenant AND marketplace=:market "
                        "AND external_id=:id"
                    ),
                    {
                        "tenant": TENANT_ID,
                        "market": target.marketplace,
                        "id": target.external_id,
                    },
                )
                task = asyncio.create_task(
                    make_runner(integration, (target,), arrived=arrived).run(
                        integration.source_url or ""
                    )
                )
                pending_workers.append(task)
                await asyncio.wait_for(arrived.wait(), timeout=5)
                await asyncio.sleep(0.1)
                check("relink race is serialized", not task.done())
            try:
                await asyncio.wait_for(task, timeout=10)
            except PriceRefreshScopeError:
                pass
            else:
                raise AssertionError("Refresh reapproved an unlinked offer")
            check(
                "administrative unlink not reversed",
                (await read_target()).canonical_product_id is None,
            )
            check(
                "rejected relink creates no history",
                await history_size() == history_before,
            )
            async with scope() as repos:
                await repos.offers.save(TENANT_ID, current)

            async with scope() as repos:
                snapshots = {
                    (o.marketplace, o.external_id): o
                    for o in await repos.offers.list_by_tenant(TENANT_ID)
                }

            def factory_runner(
                source: MarketplaceIntegration,
            ) -> MarketplaceApplicationRunner:
                incoming = tuple(
                    o
                    for key, o in snapshots.items()
                    if key[0] == source.marketplace and key[1] in targets[source.id]
                )
                return make_runner(source, incoming)

            components = create_postgres_runtime_components(
                SchedulerSettings(lease_enabled=True), session_factory=factory
            )
            process = RuntimeProcess(components)
            service = MarketplaceIntegrationExecutionService(
                repository_scope_factory=scope,
                runner_factories={"ggsel": factory_runner, "funpay": factory_runner},
                integration_ids=frozenset(targets),
            )
            job = EnabledMarketplaceIntegrationsJob(service)
            process.register_job(job, RuntimeJobConfig(interval_seconds=1))
            process.start()
            try:
                for _ in range(100):
                    if process.list_statuses()[0].run_count:
                        break
                    await asyncio.sleep(0.1)
                check(
                    "Scheduler executes existing integration job",
                    process.list_statuses()[0].run_count >= 1,
                )
            finally:
                await process.stop()
            job_result = job.last_result
            check(
                "all six Scheduler executions succeed",
                isinstance(job_result, MarketplaceIntegrationExecutionBatch)
                and job_result.failed_integrations == 0,
            )

        await engine.dispose()
        fresh_engine = create_async_engine(url)
        try:
            fresh_factory = async_sessionmaker(fresh_engine, expire_on_commit=False)
            fresh_scope = create_postgres_repository_scope(fresh_factory)
            check(
                "fresh-engine six-offer scope retained",
                len(await load_refresh_targets(fresh_scope)) == 6,
            )
            public = create_postgres_public_read_repository_scope(fresh_factory)
            async with public() as public_repos:
                for product_id in set(APPROVED_OFFERS.values()):
                    comparison = await public_repos.comparisons.get_comparison(
                        product_id, TENANT_ID
                    )
                    check(
                        "fresh public comparison has two durable offers",
                        comparison is not None
                        and len(comparison.offers) == 2
                        and comparison.product is not None
                        and comparison.product.updated_at is not None,
                    )
            async with fresh_engine.connect() as conn:
                for table, previous in immutable_before.items():
                    rows = {
                        str(row[0]): str(row[1])
                        for row in (
                            await conn.execute(
                                text(
                                    "SELECT id::text,md5(row_to_json(t)::text) "
                                    f"FROM {table} t ORDER BY id"
                                )
                            )
                        ).all()
                    }
                    check("products/decisions/audits unchanged", rows == previous)
        finally:
            await fresh_engine.dispose()
        print(
            f"PASS {len(checks)} PostgreSQL checks; synthetic prices, "
            "no marketplace/AI/Telegram calls."
        )
        return 0
    finally:
        for worker in pending_workers:
            if not worker.done():
                worker.cancel()
        await asyncio.gather(*pending_workers, return_exceptions=True)
        await engine.dispose()
        await default_engine.dispose()


if __name__ == "__main__":
    configured_url = os.getenv(DATABASE_ENV, "")
    if not configured_url:
        print(
            f"Set {DATABASE_ENV} to an isolated restored catalog copy; no skip result."
        )
        raise SystemExit(2)
    raise SystemExit(asyncio.run(verify(configured_url)))
