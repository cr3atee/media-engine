"""Read-only quote evidence must stay scoped to its offer, source and tenant."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.schemas.public import PublicOfferSummary
from app.catalog.hierarchy import CatalogSourceRule
from app.config.settings import AdminApiSettings
from app.domain.marketplace_integrations import MarketplaceIntegration
from app.domain.price_snapshot import PriceSnapshot
from app.domain.tenancy import Tenant
from app.main import create_app
from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer
from app.repositories.provider import RepositoryProvider, create_memory_provider
from app.repositories.public_queries.models import PublicOfferQuery, PublicProductQuery
from app.repositories.public_queries.repository_backed import (
    RepositoryBackedPublicReadRepository,
    create_repository_backed_public_read_scope_factory,
)
from app.repositories.queries.models import PageRequest

NOW = datetime(2026, 11, 25, 6, tzinfo=UTC)
FAILED = NOW + timedelta(minutes=5)
TENANT = UUID(int=25201)
PRODUCT = UUID(int=25202)
INTEGRATION = UUID(int=25203)
RULE = UUID(int=25204)
PAGE = PageRequest(limit=10, sort="price", direction="asc", filter_hash="test")


async def _seed() -> tuple[RepositoryProvider, ParsedOffer, MarketplaceIntegration]:
    provider = create_memory_provider()
    await provider.tenants.create(
        Tenant(
            id=TENANT, name="Offline", slug="offline", created_at=NOW, updated_at=NOW
        )
    )
    await provider.canonical_products.save(
        CanonicalProduct(
            id=PRODUCT,
            tenant_id=TENANT,
            name="Offline product",
            category=None,
            aliases=(),
        )
    )
    integration = MarketplaceIntegration(
        id=INTEGRATION,
        tenant_id=TENANT,
        marketplace="ggsel",
        display_name="Offline source",
        source_url="https://example.com/source",
        created_at=NOW,
        updated_at=FAILED,
        last_successful_run_at=NOW,
        last_failed_run_at=FAILED,
        last_error_code="InternalSourceError",
        last_error_summary="Private diagnostics must not enter the public DTO",
    )
    await provider.marketplace_integrations.save(integration)
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
    offer = ParsedOffer(
        tenant_id=TENANT,
        marketplace="ggsel",
        external_id="offline-offer",
        title="Offline subscription",
        url="https://example.com/item",
        price=Decimal("80"),
        currency="RUB",
        canonical_product_id=PRODUCT,
        catalog_source_rule_id=RULE,
        source_category_id="1",
        catalog_hub_code="exitlag",
        catalog_section_code="subscriptions",
    )
    await provider.offers.save(offer)
    await provider.price_history.add(
        PriceSnapshot(
            tenant_id=TENANT,
            marketplace="ggsel",
            external_id="offline-offer",
            price=Decimal("80"),
            currency="RUB",
            collected_at=NOW,
        )
    )
    return provider, offer, integration


def test_list_comparison_and_best_offer_share_quote_evidence() -> None:
    async def scenario() -> None:
        provider, offer, _ = await _seed()
        second = replace(
            offer,
            marketplace="funpay",
            external_id="other",
            price=Decimal("100"),
            catalog_source_rule_id=None,
        )
        await provider.offers.save(second)
        repository = RepositoryBackedPublicReadRepository(provider)
        listed = await repository.list_offers(PublicOfferQuery(tenant_id=TENANT), PAGE)
        comparison = await repository.get_comparison(PRODUCT, TENANT)
        assert comparison is not None and comparison.best_offer is not None
        expected = next(o for o in listed.items if o.marketplace == "ggsel")
        assert expected.price_observed_at == NOW and expected.source_failed_at == FAILED
        assert comparison.best_offer == expected
        assert expected in comparison.offers
        assert comparison.differences[0].offer.source_failed_at is None
        assert comparison.differences[0].offer.price_observed_at is None
        card = await repository.list_products(
            PublicProductQuery(tenant_id=TENANT), PAGE
        )
        assert card.items[0].best_offer == expected
        assert (
            await provider.offers.get_by_identity(TENANT, "ggsel", "offline-offer")
            == offer
        )

    asyncio.run(scenario())


@pytest.mark.parametrize("case", ["missing", "price", "currency"])
def test_mismatched_or_missing_history_does_not_claim_observed_price(case: str) -> None:
    async def scenario() -> None:
        provider, offer, _ = await _seed()
        if case == "missing":
            offer = replace(offer, external_id="not-observed")
        elif case == "price":
            offer = replace(offer, price=Decimal("81"))
        else:
            offer = replace(offer, currency="USD")
        await provider.offers.save(offer)
        result = await RepositoryBackedPublicReadRepository(provider).list_offers(
            PublicOfferQuery(tenant_id=TENANT, min_price=offer.price), PAGE
        )
        current = next(o for o in result.items if o.external_id == offer.external_id)
        assert current.price_observed_at is None
        assert current.source_failed_at == FAILED

    asyncio.run(scenario())


@pytest.mark.parametrize("case", ["before_observation", "equal", "recovered"])
def test_old_or_recovered_source_failure_does_not_mask_new_evidence(case: str) -> None:
    async def scenario() -> None:
        provider, _, integration = await _seed()
        if case == "recovered":
            integration = replace(integration, last_successful_run_at=FAILED)
        else:
            integration = replace(
                integration,
                last_failed_run_at=NOW - timedelta(seconds=1)
                if case == "before_observation"
                else NOW,
            )
        await provider.marketplace_integrations.save(integration)
        result = await RepositoryBackedPublicReadRepository(provider).get_comparison(
            PRODUCT, TENANT
        )
        assert result is not None
        assert result.offers[0].price_observed_at == NOW
        assert result.offers[0].source_failed_at is None

    asyncio.run(scenario())


@pytest.mark.parametrize("case", ["missing_rule", "category", "marketplace", "foreign"])
def test_unrelated_source_cannot_supply_failure(case: str) -> None:
    async def scenario() -> None:
        provider, offer, integration = await _seed()
        if case == "missing_rule":
            offer = replace(offer, catalog_source_rule_id=UUID(int=999))
        elif case == "category":
            offer = replace(offer, source_category_id="other")
        elif case == "marketplace":
            await provider.marketplace_integrations.save(
                replace(integration, marketplace="funpay")
            )
        else:
            foreign = replace(integration, id=UUID(int=998), tenant_id=UUID(int=997))
            await provider.marketplace_integrations.save(foreign)
            rule = (await provider.catalog_source_rules.list_by_tenant(TENANT))[0]
            await provider.catalog_source_rules.save(
                replace(rule, integration_id=foreign.id)
            )
        await provider.offers.save(offer)
        result = await RepositoryBackedPublicReadRepository(provider).get_comparison(
            PRODUCT, TENANT
        )
        assert result is not None
        assert result.offers[0].source_failed_at is None

    asyncio.run(scenario())


def test_public_api_exposes_only_evidence_not_internal_source_metadata() -> None:
    provider, _, _ = asyncio.run(_seed())
    client = TestClient(
        create_app(
            admin_api_settings=AdminApiSettings(api_enabled=False),
            public_read_repository_scope_factory=(
                create_repository_backed_public_read_scope_factory(provider)
            ),
        )
    )
    response = client.get(f"/api/v1/public/products/{PRODUCT}/comparison")
    assert response.status_code == 200
    body = response.json()
    assert body["offers"][0]["price_observed_at"] == "2026-11-25T06:00:00Z"
    assert body["offers"][0]["source_failed_at"] == "2026-11-25T06:05:00Z"
    assert body["best_offer"] == body["offers"][0]
    assert "InternalSourceError" not in response.text
    assert "Private diagnostics" not in response.text
    assert str(INTEGRATION) not in response.text
    assert str(TENANT) not in response.text


def test_same_marketplace_id_in_another_tenant_cannot_supply_evidence() -> None:
    async def scenario() -> None:
        provider, offer, _ = await _seed()
        foreign_tenant, foreign_product = UUID(int=25301), UUID(int=25302)
        await provider.tenants.create(
            Tenant(
                id=foreign_tenant,
                name="Other",
                slug="other",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await provider.canonical_products.save(
            CanonicalProduct(
                id=foreign_product,
                tenant_id=foreign_tenant,
                name="Other product",
                category=None,
                aliases=(),
            )
        )
        await provider.offers.save(
            replace(
                offer, tenant_id=foreign_tenant, canonical_product_id=foreign_product
            )
        )
        await provider.price_history.add(
            PriceSnapshot(
                tenant_id=foreign_tenant,
                marketplace="ggsel",
                external_id="offline-offer",
                price=Decimal("80"),
                currency="RUB",
                collected_at=NOW + timedelta(hours=1),
            )
        )
        repository = RepositoryBackedPublicReadRepository(provider)
        original = await repository.get_comparison(PRODUCT, TENANT)
        foreign = await repository.get_comparison(foreign_product, foreign_tenant)
        assert original is not None and foreign is not None
        assert original.offers[0].price_observed_at == NOW
        assert original.offers[0].source_failed_at == FAILED
        assert foreign.offers[0].price_observed_at == NOW + timedelta(hours=1)
        assert foreign.offers[0].source_failed_at is None
        assert await repository.get_comparison(PRODUCT, foreign_tenant) is None

    asyncio.run(scenario())


@pytest.mark.parametrize("field", ["price_observed_at", "source_failed_at"])
def test_public_evidence_dates_require_timezone(field: str) -> None:
    payload: dict[str, object] = {
        "marketplace": "ggsel",
        "external_id": "offline",
        "title": None,
        "url": None,
        "price": "80",
        "currency": "RUB",
        field: datetime(2026, 11, 25, 17, tzinfo=timezone(timedelta(hours=11))),
    }
    dto = PublicOfferSummary.model_validate(payload)
    assert getattr(dto, field) == NOW
    payload[field] = datetime(2026, 11, 25, 17)
    with pytest.raises(ValidationError):
        PublicOfferSummary.model_validate(payload)
