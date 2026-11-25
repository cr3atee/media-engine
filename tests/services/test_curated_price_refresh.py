"""Offline checks for bounded refreshes; these quotes are synthetic test data."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import httpx
import pytest

from app.catalog.hierarchy import CatalogSourceRule
from app.core.http_client import HttpClient
from app.domain.activation_conditions import (
    AccountRequirement,
    ActivationConditions,
    DeliveryMethod,
)
from app.domain.marketplace import Marketplace
from app.domain.marketplace_integrations import (
    MarketplaceIntegration,
    MarketplaceIntegrationStatus,
)
from app.domain.tenancy import Tenant
from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer
from app.repositories.provider import RepositoryProvider, create_memory_provider
from app.runtime.curated_prices import (
    MarketplacePollingCooldownError,
    PollingHttpClient,
)
from app.runtime.marketplaces import create_marketplace_processing_pipeline
from app.services.marketplace_application_runner import (
    MarketplaceApplicationRunner,
    PriceRefreshScopeError,
)
from app.services.marketplace_integration_execution import (
    MarketplaceIntegrationExecutionService,
)
from app.services.repository_scope import create_memory_repository_scope
from scripts.run_epic25_price_refresh import parse_args, require_local_catalog

TENANT = UUID(int=25101)
PRODUCT = UUID(int=25102)
INTEGRATION = UUID(int=25103)
RULE = UUID(int=25104)
NOW = datetime(2026, 11, 24, tzinfo=UTC)
URL = "https://ggsel.net/en/catalog/exitlag"


def _conditions() -> ActivationConditions:
    """Return explicit offline-only conditions, never inferred marketplace facts."""
    return ActivationConditions(
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


async def _seed() -> tuple[RepositoryProvider, ParsedOffer]:
    provider = create_memory_provider()
    await provider.tenants.create(
        Tenant(
            id=TENANT,
            name="Offline fixture",
            slug="offline-refresh",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await provider.canonical_products.save(
        CanonicalProduct(
            id=PRODUCT,
            tenant_id=TENANT,
            name="Offline subscription",
            category=None,
            aliases=(),
        )
    )
    await provider.marketplace_integrations.save(
        MarketplaceIntegration(
            id=INTEGRATION,
            tenant_id=TENANT,
            marketplace="ggsel",
            display_name="Offline source",
            source_url=URL,
            enabled=True,
            status=MarketplaceIntegrationStatus.ACTIVE,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await provider.catalog_source_rules.save(
        CatalogSourceRule(
            id=RULE,
            tenant_id=TENANT,
            integration_id=INTEGRATION,
            marketplace="ggsel",
            source_category_id="1",
            hub_code="exitlag",
            section_code="subscriptions",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    stored = ParsedOffer(
        tenant_id=TENANT,
        marketplace="ggsel",
        external_id="100",
        title="Offline subscription",
        url="https://ggsel.net/item/100",
        price=Decimal("100"),
        currency="RUB",
        seller_id="seller-1",
        seller_name="Offline seller",
        source_category_id="1",
        catalog_hub_code="exitlag",
        catalog_section_code="subscriptions",
        catalog_source_rule_id=RULE,
        canonical_product_id=PRODUCT,
        activation_conditions=_conditions(),
    )
    await provider.offers.save(TENANT, stored)
    return provider, stored


async def _run(provider: RepositoryProvider, offers: tuple[ParsedOffer, ...]) -> None:
    async def ingest(url: str) -> tuple[ParsedOffer, ...]:
        assert url == URL
        return offers

    async with HttpClient() as http:
        runner = MarketplaceApplicationRunner(
            marketplace=Marketplace.GGSEL,
            ingestion=ingest,
            repository_scope_factory=create_memory_repository_scope(provider),
            pipeline=create_marketplace_processing_pipeline(http),
            tenant_id=TENANT,
            integration_id=INTEGRATION,
            price_refresh_targets={"100": PRODUCT},
        )
        result = await runner.run(URL)
        assert result.offers_persisted == 1 and result.snapshots_persisted == 1
        assert result.offers_deactivated == 0


def test_only_price_changes_and_unapproved_input_is_not_saved() -> None:
    async def scenario() -> None:
        provider, old = await _seed()
        fresh = replace(
            old,
            price=Decimal("80"),
            activation_conditions=None,
            canonical_product_id=None,
            catalog_source_rule_id=None,
        )
        await _run(provider, (fresh, replace(fresh, external_id="999")))
        stored = await provider.offers.get_by_identity(TENANT, "ggsel", "100")
        assert stored == replace(old, price=Decimal("80"))
        assert len(await provider.offers.list_by_tenant(TENANT)) == 1
        snapshot = await provider.price_history.get_last(TENANT, "ggsel", "100")
        assert snapshot is not None and snapshot.price == Decimal("80")
        assert snapshot.collected_at > NOW

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "change",
    [
        {"price": None},
        {"price": Decimal("0")},
        {"price": Decimal("-1")},
        {"price": Decimal("NaN")},
        {"price": Decimal("Infinity")},
        {"currency": "USD"},
        {"title": "Different period"},
        {"seller_id": "changed"},
        {"seller_name": "changed"},
        {"url": "https://example.com/changed"},
        {"source_category_id": "other"},
    ],
)
def test_invalid_quote_preserves_price_and_history(change: dict[str, object]) -> None:
    async def scenario() -> None:
        provider, old = await _seed()
        with pytest.raises(PriceRefreshScopeError):
            await _run(provider, (replace(old, **change),))  # type: ignore[arg-type]
        assert await provider.offers.get_by_identity(TENANT, "ggsel", "100") == old
        assert await provider.price_history.get_last(TENANT, "ggsel", "100") is None

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "duplicate",
        "marketplace",
        "relinked",
        "retired",
        "disabled",
        "rule_changed",
    ],
)
def test_scope_failures_never_recreate_or_reapprove(case: str) -> None:
    async def scenario() -> None:
        provider, old = await _seed()
        offers: tuple[ParsedOffer, ...] = (replace(old, price=Decimal("80")),)
        if case == "missing":
            offers = ()
        if case == "duplicate":
            offers = offers + offers
        if case == "marketplace":
            offers = (replace(offers[0], marketplace="funpay"),)
        if case == "relinked":
            await provider.offers.save(
                TENANT, replace(old, canonical_product_id=UUID(int=25199))
            )
        if case == "retired":
            from app.domain.offer_availability import OfferAvailabilityStatus

            await provider.offers.set_availability_status(
                TENANT, "ggsel", "100", OfferAvailabilityStatus.RETIRED, NOW, 1
            )
        if case == "disabled":
            integration = await provider.marketplace_integrations.get_by_tenant_and_id(
                TENANT, INTEGRATION
            )
            assert integration is not None
            await provider.marketplace_integrations.save(
                replace(integration, enabled=False)
            )
        if case == "rule_changed":
            rule = await provider.catalog_source_rules.get_by_source(
                TENANT, INTEGRATION, "ggsel", "1"
            )
            assert rule is not None
            await provider.catalog_source_rules.save(replace(rule, hub_code="spotify"))
        with pytest.raises(PriceRefreshScopeError):
            await _run(provider, offers)
        assert await provider.price_history.get_last(TENANT, "ggsel", "100") is None

    asyncio.run(scenario())


def test_execution_service_filters_integration_ids_before_factory_calls() -> None:
    async def scenario() -> None:
        provider, _ = await _seed()
        result = await MarketplaceIntegrationExecutionService(
            repository_scope_factory=create_memory_repository_scope(provider),
            runner_factories={},
            integration_ids=frozenset(),
        ).run_enabled_integrations()
        assert result.selected_integrations == 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "header", ["3600", "Tue, 24 Nov 2026 02:00:00 GMT", "invalid", "NaN", "-1"]
)
@pytest.mark.parametrize("status", [403, 429])
def test_rate_limit_blocks_next_call_and_does_not_block_other_marketplace(
    monkeypatch: pytest.MonkeyPatch,
    header: str,
    status: int,
) -> None:
    async def scenario() -> None:
        calls: list[str] = []
        now = [NOW]

        async def request(
            self: HttpClient, method: str, url: str, **kwargs: object
        ) -> httpx.Response:
            calls.append(url)
            return httpx.Response(
                status if "ggsel" in url else 200, headers={"Retry-After": header}
            )

        monkeypatch.setattr(HttpClient, "_request", request)
        async with PollingHttpClient(clock=lambda: now[0]) as http:
            assert (await http.get("https://api.ggsel.com/first")).status_code == status
            with pytest.raises(MarketplacePollingCooldownError):
                await http.get("https://api.ggsel.com/second")
            now[0] += timedelta(seconds=2)
            assert (await http.get("https://funpay.com/lots/1/")).status_code == 200
            assert len(calls) == 2
            assert http._blocked_until["api.ggsel.com"] >= NOW + timedelta(minutes=30)
            if header in {"3600", "Tue, 24 Nov 2026 02:00:00 GMT"}:
                assert http._blocked_until["api.ggsel.com"] >= NOW + timedelta(hours=1)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "url",
    [
        "http://funpay.com/",
        "https://127.0.0.1/",
        "https://funpay.com.evil.test/",
        "https://x:y@funpay.com/",
        "https://funpay.com:444/",
    ],
)
def test_polling_client_rejects_untrusted_destinations(url: str) -> None:
    async def scenario() -> None:
        async with PollingHttpClient() as http:
            with pytest.raises(ValueError):
                await http.get(url)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "args",
    [
        ["--interval-seconds", "1"],
        ["--duration-seconds", "nan"],
        ["--duration-seconds", "-1"],
        ["--once", "--defer-first-run"],
    ],
)
def test_cli_refuses_aggressive_or_invalid_schedule(args: list[str]) -> None:
    with pytest.raises(SystemExit):
        parse_args(args)


def test_cli_rejects_review_and_production_database_urls() -> None:
    for url in (
        "postgresql+asyncpg://user:secret@database.example/production",
        "postgresql+asyncpg://user:secret@127.0.0.1/epic23_catalog_review_epic25_manual",
    ):
        with pytest.raises((RuntimeError, ValueError)):
            require_local_catalog(url)


def test_funpay_hostname_alias_cannot_bypass_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        calls: list[str] = []

        async def request(
            self: HttpClient, method: str, url: str, **kwargs: object
        ) -> httpx.Response:
            calls.append(url)
            return httpx.Response(403)

        monkeypatch.setattr(HttpClient, "_request", request)
        async with PollingHttpClient(clock=lambda: NOW) as http:
            await http.get("https://funpay.com/lots/1/")
            with pytest.raises(MarketplacePollingCooldownError):
                await http.get("https://www.funpay.com/lots/2/")
        assert len(calls) == 1

    asyncio.run(scenario())


def test_http_pacing_is_applied_between_successful_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        delays: list[float] = []

        async def request(
            self: HttpClient, method: str, url: str, **kwargs: object
        ) -> httpx.Response:
            return httpx.Response(200)

        async def sleep(seconds: float) -> None:
            delays.append(seconds)

        monkeypatch.setattr(HttpClient, "_request", request)
        monkeypatch.setattr(asyncio, "sleep", sleep)
        async with PollingHttpClient(clock=lambda: NOW) as http:
            await http.get("https://api.ggsel.com/first")
            await http.get("https://funpay.com/lots/1/")
        assert delays == [1.0]

    asyncio.run(scenario())


def test_deferred_launcher_stops_scheduler_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise launcher lifecycle without opening a DB or marketplace connection."""
    from app.config.settings import SchedulerSettings
    from app.runtime.bootstrap import (
        RuntimeComponents,
        create_memory_runtime_components,
    )
    from app.runtime.process import RuntimeProcess
    from app.services.repository_scope import RepositoryScopeFactory
    from scripts import run_epic25_price_refresh as launcher

    async def scenario() -> None:
        stopped: list[bool] = []
        original_stop = RuntimeProcess.stop

        async def track_stop(self: RuntimeProcess) -> None:
            stopped.append(True)
            await original_stop(self)

        def memory_components(
            settings: SchedulerSettings,
            *,
            session_factory: object,
        ) -> RuntimeComponents:
            return create_memory_runtime_components(
                SchedulerSettings(lease_enabled=False)
            )

        async def targets(scope: RepositoryScopeFactory) -> dict[UUID, dict[str, UUID]]:
            return {INTEGRATION: {"100": PRODUCT}}

        async def wait(
            event: asyncio.Event,
            *,
            duration_seconds: float | None,
        ) -> None:
            await asyncio.sleep(0)

        monkeypatch.setattr(
            launcher, "create_postgres_runtime_components", memory_components
        )
        monkeypatch.setattr(launcher, "load_refresh_targets", targets)
        monkeypatch.setattr(launcher, "_wait_for_shutdown", wait)
        monkeypatch.setattr(RuntimeProcess, "stop", track_stop)
        monkeypatch.setenv(launcher.LIVE_ENV, launcher.LIVE_GUARD)
        args = launcher.parse_args(["--defer-first-run", "--duration-seconds", "1"])
        code = await launcher.run(
            args,
            "postgresql+asyncpg://offline@127.0.0.1/"
            "epic23_catalog_review_epic25_price_refresh_test",
        )
        await asyncio.sleep(0)
        assert code == 0 and len(stopped) == 1

    asyncio.run(scenario())
