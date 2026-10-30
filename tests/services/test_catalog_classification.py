from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from app.catalog.hierarchy import CatalogHub, CatalogSection
from app.domain.marketplace_integrations import (
    MarketplaceIntegration,
    MarketplaceIntegrationStatus,
)
from app.parsers.models import ParsedOffer
from app.repositories.provider import RepositoryProvider, create_memory_provider
from app.services.catalog_classification import (
    CatalogClassificationService,
    CatalogClassificationServiceError,
    CreateCatalogSourceRuleCommand,
    UpdateCatalogSourceRuleCommand,
)
from app.services.repository_scope import create_memory_repository_scope

TENANT_A = UUID("10000000-0000-4000-8000-000000000001")
TENANT_B = UUID("10000000-0000-4000-8000-000000000002")
INTEGRATION_A = UUID("20000000-0000-4000-8000-000000000001")
INTEGRATION_B = UUID("20000000-0000-4000-8000-000000000002")
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run async service methods without a pytest plugin."""
    return asyncio.run(awaitable)


def test_create_and_update_rule_with_optimistic_version() -> None:
    provider = _provider()
    service = _service(provider)
    created = run_async(service.create_rule(_create_command()))

    assert created.version == 1
    assert created.hub_code == "fortnite"
    assert created.section_code == "v-bucks"
    assert tuple(run_async(service.list_rules(TENANT_A, INTEGRATION_A))) == (created,)

    updated = run_async(
        service.update_rule(
            UpdateCatalogSourceRuleCommand(
                tenant_id=TENANT_A,
                integration_id=INTEGRATION_A,
                marketplace="playerok",
                source_category_id="fortnite-products",
                source_category_name="Fortnite accounts",
                hub_code="fortnite",
                section_code="accounts",
                expected_version=1,
            )
        )
    )

    assert updated.version == 2
    assert updated.section_code == "accounts"
    assert updated.updated_at == NOW + timedelta(minutes=1)

    with pytest.raises(
        CatalogClassificationServiceError,
        match="expected version",
    ) as stale:
        run_async(
            service.update_rule(
                UpdateCatalogSourceRuleCommand(
                    tenant_id=TENANT_A,
                    integration_id=INTEGRATION_A,
                    marketplace="playerok",
                    source_category_id="fortnite-products",
                    hub_code="fortnite",
                    section_code="v-bucks",
                    expected_version=1,
                )
            )
        )
    assert stale.value.code == "optimistic_concurrency_conflict"
    assert stale.value.details == {"current_version": 2}


def test_create_rule_rejects_duplicate_invalid_target_and_wrong_marketplace() -> None:
    provider = _provider()
    service = _service(provider)
    run_async(service.create_rule(_create_command()))

    with pytest.raises(CatalogClassificationServiceError) as duplicate:
        run_async(service.create_rule(_create_command()))
    assert duplicate.value.code == "catalog_source_rule_conflict"

    with pytest.raises(CatalogClassificationServiceError) as hub:
        run_async(
            service.create_rule(_create_command(source_category_id="other", hub="x"))
        )
    assert hub.value.code == "catalog_hub_not_found"

    with pytest.raises(CatalogClassificationServiceError) as section:
        run_async(
            service.create_rule(
                _create_command(source_category_id="other", section="missing")
            )
        )
    assert section.value.code == "catalog_section_not_found"

    with pytest.raises(CatalogClassificationServiceError) as marketplace:
        run_async(
            service.create_rule(
                _create_command(source_category_id="other", marketplace="ggsel")
            )
        )
    assert marketplace.value.code == "catalog_source_marketplace_mismatch"


def test_classification_uses_exact_rules_and_never_guesses_from_title() -> None:
    provider = _provider()
    service = _service(provider)
    rule = run_async(service.create_rule(_create_command()))
    offers = (
        _offer("known", source_category_id="fortnite-products"),
        _offer(
            "unknown",
            source_category_id="unknown",
            title="Fortnite V-Bucks account rental",
        ),
        _offer("missing", source_category_id=None),
    )

    results = run_async(service.classify_offers(TENANT_A, INTEGRATION_A, offers))

    assert results[0].classification is not None
    assert results[0].classification.hub.code == "fortnite"
    assert results[0].classification.section.code == "v-bucks"
    assert results[0].rule_id == rule.id
    assert results[0].apply() == replace(
        offers[0],
        catalog_hub_code="fortnite",
        catalog_section_code="v-bucks",
        catalog_source_rule_id=rule.id,
    )
    assert results[1].classification is None
    assert results[1].rule_id is None
    assert results[1].apply().catalog_hub_code is None
    assert results[1].apply().catalog_section_code is None
    assert results[1].apply().catalog_source_rule_id is None
    assert results[2].classification is None
    assert results[2].rule_id is None


def test_same_source_category_can_be_scoped_to_different_integrations() -> None:
    provider = _provider(include_second_integration=True)
    identifiers = iter((UUID(int=50_001), UUID(int=50_002)))
    service = _service(provider, identifiers=identifiers)
    run_async(service.create_rule(_create_command()))
    run_async(
        service.create_rule(
            _create_command(
                integration_id=INTEGRATION_B,
                section="accounts",
            )
        )
    )

    first = run_async(
        service.classify_offers(
            TENANT_A,
            INTEGRATION_A,
            (_offer("a", source_category_id="fortnite-products"),),
        )
    )
    second = run_async(
        service.classify_offers(
            TENANT_A,
            INTEGRATION_B,
            (_offer("b", source_category_id="fortnite-products"),),
        )
    )

    assert first[0].classification is not None
    assert first[0].classification.section.code == "v-bucks"
    assert second[0].classification is not None
    assert second[0].classification.section.code == "accounts"


def test_classification_rejects_cross_tenant_and_marketplace_offers() -> None:
    provider = _provider()
    service = _service(provider)

    with pytest.raises(CatalogClassificationServiceError) as tenant:
        run_async(
            service.classify_offers(
                TENANT_A,
                INTEGRATION_A,
                (
                    _offer(
                        "tenant-b",
                        source_category_id="fortnite-products",
                        tenant_id=TENANT_B,
                    ),
                ),
            )
        )
    assert tenant.value.code == "catalog_offer_tenant_mismatch"

    with pytest.raises(CatalogClassificationServiceError) as marketplace:
        run_async(
            service.classify_offers(
                TENANT_A,
                INTEGRATION_A,
                (
                    _offer(
                        "ggsel",
                        source_category_id="fortnite-products",
                        marketplace="ggsel",
                    ),
                ),
            )
        )
    assert marketplace.value.code == "catalog_offer_marketplace_mismatch"


def _provider(*, include_second_integration: bool = False) -> RepositoryProvider:
    provider = create_memory_provider()
    run_async(
        provider.marketplace_integrations.save(
            _integration(INTEGRATION_A, "Fortnite V-Bucks")
        )
    )
    if include_second_integration:
        run_async(
            provider.marketplace_integrations.save(
                _integration(INTEGRATION_B, "Fortnite accounts")
            )
        )
    return provider


def _integration(integration_id: UUID, name: str) -> MarketplaceIntegration:
    return MarketplaceIntegration(
        id=integration_id,
        tenant_id=TENANT_A,
        marketplace="playerok",
        display_name=name,
        enabled=True,
        status=MarketplaceIntegrationStatus.ACTIVE,
        source_url=f"https://playerok.com/catalog/{integration_id}",
        created_at=NOW,
        updated_at=NOW,
    )


def _service(
    provider: RepositoryProvider,
    *,
    identifiers: Iterator[UUID] | None = None,
) -> CatalogClassificationService:
    ids = identifiers or iter(tuple(UUID(int=50_001 + index) for index in range(10)))
    times = iter((NOW, NOW + timedelta(minutes=1), NOW + timedelta(minutes=2)))
    return CatalogClassificationService(
        create_memory_repository_scope(provider),
        (_fortnite(),),
        clock=lambda: next(times),
        rule_id_factory=lambda: next(ids),
    )


def _fortnite() -> CatalogHub:
    return CatalogHub(
        code="fortnite",
        name="Fortnite",
        sections=(
            CatalogSection(code="v-bucks", name="В-баксы", offer_type="topups"),
            CatalogSection(
                code="accounts",
                name="Аккаунты",
                offer_type="accounts",
            ),
            CatalogSection(code="rental", name="Аренда"),
        ),
    )


def _create_command(
    *,
    integration_id: UUID = INTEGRATION_A,
    source_category_id: str = "fortnite-products",
    marketplace: str = "playerok",
    hub: str = "fortnite",
    section: str = "v-bucks",
) -> CreateCatalogSourceRuleCommand:
    return CreateCatalogSourceRuleCommand(
        tenant_id=TENANT_A,
        integration_id=integration_id,
        marketplace=marketplace,
        source_category_id=source_category_id,
        source_category_name="Fortnite products",
        hub_code=hub,
        section_code=section,
    )


def _offer(
    external_id: str,
    *,
    source_category_id: str | None,
    title: str = "Marketplace offer",
    tenant_id: UUID = TENANT_A,
    marketplace: str = "playerok",
) -> ParsedOffer:
    return ParsedOffer(
        tenant_id=tenant_id,
        marketplace=marketplace,
        external_id=external_id,
        title=title,
        url=f"https://example.com/{external_id}",
        price=Decimal("790.00"),
        currency="RUB",
        source_category_id=source_category_id,
    )
