"""Synthetic discovery/intake fixtures never contact a marketplace."""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.catalog.hierarchy import CatalogSourceRule
from app.core.http_client import HttpClient
from app.database.repository_scope import create_postgres_repository_scope
from app.domain.activation_conditions import (
    AccountRequirement,
    ActivationConditions,
    DeliveryMethod,
)
from app.domain.marketplace_integrations import (
    MarketplaceIntegration,
    MarketplaceIntegrationStatus,
)
from app.domain.offer_availability import OfferAvailabilityStatus
from app.domain.tenancy import Tenant
from app.models.canonical_product import CanonicalProduct
from app.parsers.funpay_extractor import FunPayExtractor, FunPayOfferEvidence
from app.parsers.funpay_fetcher import FunPayFetcher
from app.parsers.ggsel_fetcher import GGSelFetcher
from app.parsers.models import ParsedOffer
from app.parsers.source_snapshot import SourceExtraction, SourceSnapshotEvidence
from app.repositories.provider import RepositoryProvider, create_memory_provider
from app.services.canonical_offer_review_queue import CanonicalOfferReviewQueueService
from app.services.cheaper_offer_discovery import (
    CheaperOfferCandidate,
    CheaperOfferDiscoveryService,
    CheaperOfferSourceResult,
)
from app.services.cheaper_offer_review_intake import CheaperOfferReviewIntakeService
from app.services.repository_scope import (
    RepositoryScopeFactory,
    create_memory_repository_scope,
)
from app.services.subscription_candidate_rules import LAUNCH_PRODUCTS, LAUNCH_SOURCES
from scripts.discover_epic25_cheaper_offers import (
    LIVE_ENV,
    main,
    require_review_database,
)

TENANT = UUID(int=25501)
NOW = datetime(2026, 11, 25, 10, tzinfo=UTC)
type References = dict[str, tuple[ParsedOffer, ...]]


def references() -> References:
    result: References = {}
    for index, spec in enumerate(LAUNCH_PRODUCTS):
        result[spec.hub_code] = tuple(
            ParsedOffer(
                tenant_id=TENANT,
                marketplace=marketplace,
                external_id=str(1000 + index * 10 + market_index),
                title=spec.name,
                url=f"https://ggsel.net/en/catalog/product/{1000 + index * 10}"
                if marketplace == "ggsel"
                else (
                    "https://funpay.com/lots/offer?id="
                    f"{1000 + index * 10 + market_index}"
                ),
                price=Decimal("100") if marketplace == "ggsel" else Decimal("150"),
                currency="RUB",
                seller_name="Offline seller",
                source_category_id=str(100 + index)
                if marketplace == "ggsel"
                else str(LAUNCH_SOURCES[index].category_id),
                canonical_product_id=UUID(int=25600 + index),
                catalog_hub_code=spec.hub_code,
                catalog_section_code="subscriptions",
                catalog_source_rule_id=UUID(int=25800 + index * 10 + market_index),
            )
            for market_index, marketplace in enumerate(("ggsel", "funpay"))
        )
    return result


def candidate(
    identity: str = "300", price: str = "80", marketplace: str = "ggsel"
) -> CheaperOfferCandidate:
    reference = next(o for o in references()["exitlag"] if o.marketplace == marketplace)
    return CheaperOfferCandidate(
        replace(
            reference,
            external_id=identity,
            price=Decimal(price),
            canonical_product_id=None,
            title="ExitLag 1 month subscription",
            url=f"https://ggsel.net/en/catalog/product/{identity}"
            if marketplace == "ggsel"
            else f"https://funpay.com/lots/offer?id={identity}",
        ),
        ("activation_conditions_unverified",),
    )


def report(items: tuple[CheaperOfferCandidate, ...]) -> CheaperOfferSourceResult:
    return CheaperOfferSourceResult(
        "exitlag",
        "ggsel",
        LAUNCH_PRODUCTS[0].category_url,
        NOW,
        references()["exitlag"][0],
        len(items),
        len(items),
        len(items),
        items,
    )


def mock_sources(
    monkeypatch: pytest.MonkeyPatch,
    items: tuple[CheaperOfferCandidate, ...],
    *,
    fail_funpay: bool = False,
) -> None:
    async def ggsel(
        self: CheaperOfferDiscoveryService, spec: object, reference: ParsedOffer
    ) -> tuple[int, tuple[CheaperOfferCandidate, ...]]:
        return len(items), items if reference.canonical_product_id == UUID(
            int=25600
        ) else ()

    async def funpay(
        self: CheaperOfferDiscoveryService, spec: object, reference: ParsedOffer
    ) -> tuple[int, tuple[CheaperOfferCandidate, ...]]:
        if fail_funpay:
            raise RuntimeError("private connection/cookie diagnostics must not escape")
        return 0, ()

    monkeypatch.setattr(CheaperOfferDiscoveryService, "_ggsel", ggsel)
    monkeypatch.setattr(CheaperOfferDiscoveryService, "_funpay", funpay)


def scan(refs: References, limit: int = 1) -> tuple[CheaperOfferSourceResult, ...]:
    async def scenario() -> tuple[CheaperOfferSourceResult, ...]:
        async with HttpClient() as http:
            return await CheaperOfferDiscoveryService(http, clock=lambda: NOW).scan(
                refs, limit_per_source=limit
            )

    return asyncio.run(scenario())


@pytest.mark.parametrize("reverse", [False, True])
def test_price_ranking_not_id_order_and_bounded_top_k(
    monkeypatch: pytest.MonkeyPatch, reverse: bool
) -> None:
    items = (
        candidate("1", "99"),
        candidate("900", "60.01"),
        candidate("100", "60.01"),
        candidate("2", "100"),
    )
    mock_sources(monkeypatch, items[::-1] if reverse else items)
    results = scan(references(), 2)
    assert len(results) == 6
    assert [item.offer.external_id for item in results[0].candidates] == ["100", "900"]
    assert results[0].cheaper_items == 3
    assert results[0].reference_offer.price == Decimal("100")
    assert all(
        item.offer.canonical_product_id is None for item in results[0].candidates
    )


@pytest.mark.parametrize(
    "change",
    [
        {"price": None},
        {"price": Decimal("0")},
        {"price": Decimal("-1")},
        {"price": Decimal("NaN")},
        {"price": Decimal("Infinity")},
        {"currency": "USD"},
        {"url": "https://evil.test/300"},
        {"url": "https://user:password@ggsel.net/item/300"},
        {"external_id": None},
        {"seller_name": " "},
        {"canonical_product_id": UUID(int=25600)},
        {"tenant_id": UUID(int=99999)},
        {"source_category_id": None},
    ],
)
def test_invalid_or_foreign_quotes_never_enter_ranking(
    monkeypatch: pytest.MonkeyPatch, change: dict[str, object]
) -> None:
    item = candidate()
    changed = replace(item.offer, **change)  # type: ignore[arg-type]
    mock_sources(monkeypatch, (replace(item, offer=changed),))
    assert scan(references())[0].candidates == ()


def test_approved_and_duplicate_identities_are_not_new_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approved = references()["exitlag"][0]
    mock_sources(
        monkeypatch,
        (
            candidate("300"),
            candidate("300", "1"),
            replace(
                candidate(),
                offer=replace(approved, canonical_product_id=None, price=Decimal("1")),
            ),
        ),
    )
    assert scan(references())[0].candidates == ()


@pytest.mark.parametrize(
    "case",
    [
        "missing_hub",
        "limit",
        "tenant",
        "currency",
        "unlinked",
        "shared_product",
        "wrong_hub",
        "wrong_section",
    ],
)
def test_scope_guards_fail_before_any_fetch(
    monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    refs = references()
    limit = 1
    if case == "missing_hub":
        refs.pop("spotify")
    elif case == "limit":
        limit = 4
    else:
        first = refs["exitlag"][0]
        change = (
            {"tenant_id": UUID(int=999)}
            if case == "tenant"
            else {"currency": "USD"}
            if case == "currency"
            else {"canonical_product_id": None}
            if case == "unlinked"
            else {"catalog_hub_code": "spotify"}
            if case == "wrong_hub"
            else {"catalog_section_code": "accounts"}
            if case == "wrong_section"
            else {"canonical_product_id": refs["spotify"][0].canonical_product_id}
        )
        refs["exitlag"] = (
            tuple(replace(item, **change) for item in refs["exitlag"])
            if case == "shared_product"
            else (replace(first, **change), refs["exitlag"][1])
        )

    async def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("Scope violation contacted source")

    monkeypatch.setattr(CheaperOfferDiscoveryService, "_ggsel", forbidden)
    with pytest.raises(ValueError):
        scan(refs, limit)


def test_partial_source_failure_is_sanitized_and_does_not_hide_other_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_sources(monkeypatch, (candidate(),), fail_funpay=True)
    result = scan(references())
    assert result[0].candidates
    assert sum(item.error_code == "RuntimeError" for item in result) == 3
    assert all(item.candidates == () for item in result if item.error_code)
    assert "private" not in repr(result)


def test_ggsel_screening_rejects_mixed_language_duration_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fetch(
        self: GGSelFetcher, url: str
    ) -> SourceExtraction[dict[str, object]]:
        rows = tuple(
            {
                "id_goods": i,
                "name": title,
                "url": str(i),
                "seller_name": "Offline seller",
                "id_section": 100,
                "price_wmr": 20,
            }
            for i, title in enumerate(
                ("ExitLag 1 Month", "ExitLag 1 Month / 12 месяцев", "ExitLag 3 Months"),
                301,
            )
        )
        return SourceExtraction(
            rows, SourceSnapshotEvidence(3, 3, True, "Offline fixture")
        )

    monkeypatch.setattr(GGSelFetcher, "fetch_complete_category", fetch)

    async def scenario() -> None:
        async with HttpClient() as http:
            total, items = await CheaperOfferDiscoveryService(http)._ggsel(
                LAUNCH_PRODUCTS[0], references()["exitlag"][0]
            )
        assert total == 3 and len(items) == 1
        assert items[0].offer.external_id == "301"
        assert items[0].offer.tenant_id == TENANT
        assert "activation_conditions_unverified" in items[0].review_reasons

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "method,eligible",
    [
        ("цифровой код", True),
        ("без захода на аккаунт", True),
        ("", True),
        ("акционный код (discord)", False),
    ],
)
def test_funpay_review_does_not_invent_fulfillment_or_accept_unsupported_promos(
    monkeypatch: pytest.MonkeyPatch, method: str, eligible: bool
) -> None:
    async def fetch(self: FunPayFetcher, url: str = FunPayFetcher.DEFAULT_URL) -> str:
        return "offline fixture, not a live response"

    offer = candidate("301", marketplace="funpay").offer
    evidence = FunPayOfferEvidence(
        offer, (("f-time", "1 месяц"), ("f-type", "super"), ("f-method", method))
    )

    def extract(
        self: FunPayExtractor, raw: str
    ) -> SourceExtraction[FunPayOfferEvidence]:
        return SourceExtraction(
            (evidence,), SourceSnapshotEvidence(1, 1, True, "Offline fixture")
        )

    monkeypatch.setattr(FunPayFetcher, "fetch", fetch)
    monkeypatch.setattr(FunPayExtractor, "extract_with_parameters", extract)

    async def scenario() -> None:
        async with HttpClient() as http:
            _, items = await CheaperOfferDiscoveryService(http)._funpay(
                LAUNCH_SOURCES[1], references()["duolingo"][1]
            )
        assert bool(items) is eligible
        if items:
            assert "launch_account_plan_unverified" in items[0].review_reasons
            assert items[0].offer.activation_conditions is None

    asyncio.run(scenario())


async def seed(provider: RepositoryProvider) -> None:
    await provider.tenants.create(
        Tenant(
            id=TENANT,
            name="Offline review",
            slug="offline-discovery",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    for index, (hub, offers) in enumerate(references().items()):
        product_id = offers[0].canonical_product_id
        assert product_id is not None
        await provider.canonical_products.save(
            CanonicalProduct(
                id=product_id,
                tenant_id=TENANT,
                name=LAUNCH_PRODUCTS[index].name + " Key",
                category=None,
                aliases=(),
            )
        )
        for market_index, offer in enumerate(offers):
            integration_id = UUID(int=25700 + index * 10 + market_index)
            source_url = (
                LAUNCH_PRODUCTS[index].category_url
                if offer.marketplace == "ggsel"
                else LAUNCH_SOURCES[index].category_url
            )
            await provider.marketplace_integrations.save(
                MarketplaceIntegration(
                    id=integration_id,
                    tenant_id=TENANT,
                    marketplace=offer.marketplace,
                    display_name="Offline source",
                    source_url=source_url,
                    enabled=True,
                    status=MarketplaceIntegrationStatus.ACTIVE,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            assert (
                offer.catalog_source_rule_id is not None
                and offer.source_category_id is not None
            )
            await provider.catalog_source_rules.save(
                CatalogSourceRule(
                    id=offer.catalog_source_rule_id,
                    tenant_id=TENANT,
                    integration_id=integration_id,
                    marketplace=offer.marketplace,
                    source_category_id=offer.source_category_id,
                    hub_code=hub,
                    section_code="subscriptions",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await provider.offers.save(offer)


async def assert_intake(scope: RepositoryScopeFactory) -> None:
    service = CheaperOfferReviewIntakeService(scope)
    first = await service.stage(TENANT, (report((candidate(),)),))
    second = await service.stage(TENANT, (report((candidate(),)),))
    assert first[0].status == "staged_for_review"
    assert second[0].status == "already_known"
    workspace = await CanonicalOfferReviewQueueService(scope).get_onboarding_workspace(
        TENANT
    )
    assert workspace.summary.total_offers == 7 and workspace.summary.linked_offers == 6
    assert (
        workspace.summary.canonical_products == 3
        and workspace.summary.terminal_decisions == 0
    )
    assert len(workspace.product_proposals) + len(workspace.review_candidates) == 1
    async with scope() as provider:
        stored = await provider.offers.get_by_identity(TENANT, "ggsel", "300")
        assert stored is not None and stored.canonical_product_id is None
        assert (
            stored.catalog_source_rule_id
            == references()["exitlag"][0].catalog_source_rule_id
        )
        assert await provider.price_history.get_history(TENANT, "ggsel", "300") == []
    bad = replace(
        candidate("302"), offer=replace(candidate("302").offer, tenant_id=UUID(int=999))
    )
    with pytest.raises(ValueError):
        await service.stage(TENANT, (report((candidate("301"), bad)),))
    async with scope() as provider:
        assert (
            await provider.offers.get_availability_state(TENANT, "ggsel", "301") is None
        )


def test_memory_intake_is_atomic_idempotent_and_visible_in_queue() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        await seed(provider)
        await assert_intake(create_memory_repository_scope(provider))

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "case",
    [
        "duplicate_source",
        "duplicate_identity",
        "too_many",
        "per_source",
        "profile",
        "hub",
    ],
)
def test_invalid_intake_scope_cannot_write_or_confirm_conditions(case: str) -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        await seed(provider)
        items: tuple[CheaperOfferSourceResult, ...] = (report((candidate(),)),)
        if case == "duplicate_source":
            items *= 2
        elif case == "duplicate_identity":
            items = (report((candidate(), candidate())),)
        elif case == "too_many":
            items = (report(tuple(candidate(str(300 + n)) for n in range(19))),)
        elif case == "per_source":
            items = (report(tuple(candidate(str(300 + n)) for n in range(4))),)
        elif case == "profile":
            profile = ActivationConditions(
                regions=("*",),
                excluded_regions=(),
                device="pc",
                plan="premium",
                period="P1M",
                delivery_method=DeliveryMethod.KEY,
                account_requirement=AccountRequirement.ANY,
                vpn_required=False,
                activation_window_seconds=None,
            )
            items = (
                report(
                    (
                        replace(
                            candidate(),
                            offer=replace(
                                candidate().offer, activation_conditions=profile
                            ),
                        ),
                    )
                ),
            )
        else:
            items = (
                replace(
                    items[0],
                    reference_offer=replace(
                        items[0].reference_offer, catalog_hub_code="spotify"
                    ),
                ),
            )
        with pytest.raises(ValueError):
            await CheaperOfferReviewIntakeService(
                create_memory_repository_scope(provider)
            ).stage(TENANT, items)
        assert len(await provider.offers.list_by_tenant(TENANT)) == 6
        assert not await provider.canonical_offer_decisions.list_by_tenant(TENANT)

    asyncio.run(scenario())


def test_retired_and_reviewed_rows_are_not_overwritten_or_reactivated() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        await seed(provider)
        old = references()["exitlag"][0]
        assert old.external_id is not None
        state = await provider.offers.get_availability_state(
            TENANT, "ggsel", old.external_id
        )
        assert state is not None
        await provider.offers.set_availability_status(
            TENANT,
            "ggsel",
            old.external_id,
            OfferAvailabilityStatus.RETIRED,
            NOW,
            state.version,
        )
        replacement = replace(
            candidate(),
            offer=replace(old, canonical_product_id=None, price=Decimal("1")),
        )
        result = await CheaperOfferReviewIntakeService(
            create_memory_repository_scope(provider)
        ).stage(TENANT, (report((replacement,)),))
        assert result[0].status == "already_known"
        assert (
            await provider.offers.get_by_identity(TENANT, "ggsel", old.external_id)
            is None
        )

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://u:p@production.example/production",
        "postgresql+asyncpg://u:p@127.0.0.1/epic23_catalog_review_epic25_local_catalog",
    ],
)
def test_private_intake_rejects_production_and_public_catalog(url: str) -> None:
    with pytest.raises((RuntimeError, ValueError)):
        require_review_database(url)


def test_cli_has_no_live_access_without_explicit_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(LIVE_ENV, raising=False)
    assert main([]) == 1


@pytest.mark.skipif(
    not os.getenv("EPIC25_DISCOVERY_TEST_DATABASE_URL"),
    reason="Explicit isolated PostgreSQL verification DB required",
)
def test_postgres_intake_fresh_sessions_concurrency_rollback_and_no_approval() -> None:
    async def scenario() -> None:
        url = os.environ["EPIC25_DISCOVERY_TEST_DATABASE_URL"]
        require_review_database(url)
        assert (make_url(url).database or "").startswith(
            "epic23_catalog_review_epic25_discovery_verify_"
        )
        engine = create_async_engine(url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        scope = create_postgres_repository_scope(factory)
        try:
            async with scope() as provider:
                await seed(provider)
            await assert_intake(scope)
            results = await asyncio.gather(
                *[
                    CheaperOfferReviewIntakeService(scope).stage(
                        TENANT, (report((candidate("303"),)),)
                    )
                    for _ in range(2)
                ]
            )
            assert sorted(result[0].status for result in results) == [
                "already_known",
                "staged_for_review",
            ]
            await engine.dispose()
            fresh = create_async_engine(url)
            try:
                async with create_postgres_repository_scope(
                    async_sessionmaker(fresh, expire_on_commit=False)
                )() as provider:
                    assert len(await provider.offers.list_by_tenant(TENANT)) == 8
                    assert (
                        len(await provider.canonical_products.list_by_tenant(TENANT))
                        == 3
                    )
                    assert not await provider.canonical_offer_decisions.list_by_tenant(
                        TENANT
                    )
            finally:
                await fresh.dispose()
        finally:
            await engine.dispose()

    asyncio.run(scenario())
