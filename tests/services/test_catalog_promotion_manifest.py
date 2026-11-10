from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from app.domain.admin_actions import AdminActorType
from app.domain.canonical_offer_decisions import (
    CanonicalOfferDecision,
    CanonicalOfferDecisionType,
)
from app.domain.offer_availability import OfferAvailabilityStatus
from app.domain.processing import StateTransitionOutcome
from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer
from app.repositories.provider import RepositoryProvider, create_memory_provider
from app.services.catalog_promotion_manifest import (
    CatalogPromotionManifestError,
    CatalogPromotionManifestService,
)
from app.services.repository_scope import create_memory_repository_scope

TENANT_ID = UUID("74000000-0000-4000-8000-000000000001")
FOREIGN_TENANT_ID = UUID("74000000-0000-4000-8000-000000000002")
MINECRAFT_ID = UUID("74000000-0000-4000-8000-000000000010")
FORTNITE_ID = UUID("74000000-0000-4000-8000-000000000011")
FOREIGN_PRODUCT_ID = UUID("74000000-0000-4000-8000-000000000012")
DECIDED_AT = datetime(2026, 11, 3, 8, 0, tzinfo=UTC)


def test_manifest_contains_only_active_confirmed_catalog_evidence() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        await _seed_reviewed_catalog(provider)
        before = await _repository_state(provider, TENANT_ID)

        manifest = await _service(provider).build(TENANT_ID)

        assert manifest.has_valid_digest()
        assert manifest.source_tenant_id == TENANT_ID
        assert tuple(product.id for product in manifest.products) == (MINECRAFT_ID,)
        assert tuple(
            (link.marketplace, link.external_id) for link in manifest.links
        ) == (("ggsel", "gg-active"), ("playerok", "pl-active"))
        assert manifest.links[0].source_category_id == "minecraft"
        assert manifest.links[0].catalog_hub_code == "minecraft"
        assert manifest.summary.active_offers == 3
        assert manifest.summary.canonical_products == 2
        assert manifest.summary.terminal_decisions == 4
        assert manifest.summary.confirmed_decisions == 3
        assert manifest.summary.rejected_decisions == 1
        assert manifest.summary.excluded_confirmed_decisions == 1
        assert manifest.summary.promoted_products == 1
        assert manifest.summary.promoted_links == 2
        assert await _repository_state(provider, TENANT_ID) == before

    asyncio.run(scenario())


def test_manifest_is_deterministic_across_repository_insertion_order() -> None:
    async def scenario() -> None:
        first_provider = create_memory_provider()
        second_provider = create_memory_provider()
        await _seed_reviewed_catalog(first_provider)
        await _seed_reviewed_catalog(second_provider, reverse=True)

        first = await _service(first_provider).build(TENANT_ID)
        second = await _service(second_provider).build(TENANT_ID)

        assert first.digest == second.digest
        assert first.to_json() == second.to_json()

    asyncio.run(scenario())


def test_manifest_is_tenant_isolated() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        await _seed_reviewed_catalog(provider)
        foreign_product = CanonicalProduct(
            id=FOREIGN_PRODUCT_ID,
            tenant_id=FOREIGN_TENANT_ID,
            name="Foreign product",
            category="Games",
            aliases=(),
        )
        foreign_offer = _offer(
            tenant_id=FOREIGN_TENANT_ID,
            marketplace="funpay",
            external_id="foreign-offer",
            canonical_product_id=FOREIGN_PRODUCT_ID,
        )
        await provider.canonical_products.save(foreign_product)
        await provider.offers.save(FOREIGN_TENANT_ID, foreign_offer)
        await provider.canonical_offer_decisions.append(
            _decision(
                tenant_id=FOREIGN_TENANT_ID,
                marketplace="funpay",
                external_id="foreign-offer",
                product_id=FOREIGN_PRODUCT_ID,
                outcome=CanonicalOfferDecisionType.CONFIRMED,
                ordinal=9,
            )
        )

        manifest = await _service(provider).build(TENANT_ID)

        assert all(product.id != FOREIGN_PRODUCT_ID for product in manifest.products)
        assert all(link.marketplace != "funpay" for link in manifest.links)
        assert manifest.summary.active_offers == 3
        assert manifest.summary.terminal_decisions == 4

    asyncio.run(scenario())


def test_manifest_rejects_active_link_without_confirmed_decision() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        await provider.canonical_products.save(_minecraft_product())
        await provider.offers.save(
            TENANT_ID,
            _offer(
                marketplace="ggsel",
                external_id="unreviewed",
                canonical_product_id=MINECRAFT_ID,
            ),
        )

        with pytest.raises(
            CatalogPromotionManifestError,
            match="not backed by a confirmed decision",
        ):
            await _service(provider).build(TENANT_ID)

    asyncio.run(scenario())


def test_manifest_rejects_incomplete_source_identity() -> None:
    async def scenario() -> None:
        base_offer = _offer(
            marketplace="ggsel",
            external_id="incomplete",
            canonical_product_id=MINECRAFT_ID,
        )
        cases = (
            (replace(base_offer, external_id=None), False),
            (replace(base_offer, title=None), True),
            (replace(base_offer, url=" "), True),
        )
        for offer, needs_decision in cases:
            provider = create_memory_provider()
            await provider.canonical_products.save(_minecraft_product())
            await provider.offers.save(TENANT_ID, offer)
            if needs_decision:
                await provider.canonical_offer_decisions.append(
                    _decision(
                        marketplace="ggsel",
                        external_id="incomplete",
                        product_id=MINECRAFT_ID,
                        outcome=CanonicalOfferDecisionType.CONFIRMED,
                        ordinal=1,
                    )
                )

            with pytest.raises(
                CatalogPromotionManifestError,
                match="must not be empty",
            ):
                await _service(provider).build(TENANT_ID)

    asyncio.run(scenario())


def test_manifest_rejects_product_without_launch_category() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        await provider.canonical_products.save(
            replace(_minecraft_product(), category=None)
        )
        offer = _offer(
            marketplace="ggsel",
            external_id="no-category",
            canonical_product_id=MINECRAFT_ID,
        )
        await provider.offers.save(TENANT_ID, offer)
        await provider.canonical_offer_decisions.append(
            _decision(
                marketplace="ggsel",
                external_id="no-category",
                product_id=MINECRAFT_ID,
                outcome=CanonicalOfferDecisionType.CONFIRMED,
                ordinal=1,
            )
        )

        with pytest.raises(
            CatalogPromotionManifestError,
            match="canonical product category must not be empty",
        ):
            await _service(provider).build(TENANT_ID)

    asyncio.run(scenario())


def test_manifest_rejects_empty_catalog_and_detects_tampering() -> None:
    async def scenario() -> None:
        empty_provider = create_memory_provider()
        with pytest.raises(
            CatalogPromotionManifestError,
            match="at least one active reviewed link",
        ):
            await _service(empty_provider).build(TENANT_ID)

        provider = create_memory_provider()
        await _seed_reviewed_catalog(provider)
        manifest = await _service(provider).build(TENANT_ID)
        tampered = replace(
            manifest,
            summary=replace(
                manifest.summary,
                promoted_links=manifest.summary.promoted_links + 1,
            ),
        )

        assert manifest.has_valid_digest()
        assert not tampered.has_valid_digest()

    asyncio.run(scenario())


def _service(provider: RepositoryProvider) -> CatalogPromotionManifestService:
    return CatalogPromotionManifestService(create_memory_repository_scope(provider))


async def _seed_reviewed_catalog(
    provider: RepositoryProvider,
    *,
    reverse: bool = False,
) -> None:
    products = (_minecraft_product(), _fortnite_product())
    offers = (
        _offer(
            marketplace="ggsel",
            external_id="gg-active",
            canonical_product_id=MINECRAFT_ID,
        ),
        _offer(
            marketplace="Playerok",
            external_id="pl-active",
            canonical_product_id=MINECRAFT_ID,
        ),
        _offer(
            marketplace="funpay",
            external_id="rejected-active",
            canonical_product_id=None,
        ),
        _offer(
            marketplace="ggsel",
            external_id="retired-confirmed",
            canonical_product_id=FORTNITE_ID,
        ),
    )
    decisions = (
        _decision(
            marketplace="ggsel",
            external_id="gg-active",
            product_id=MINECRAFT_ID,
            outcome=CanonicalOfferDecisionType.CONFIRMED,
            ordinal=1,
        ),
        _decision(
            marketplace="playerok",
            external_id="pl-active",
            product_id=MINECRAFT_ID,
            outcome=CanonicalOfferDecisionType.CONFIRMED,
            ordinal=2,
        ),
        _decision(
            marketplace="funpay",
            external_id="rejected-active",
            product_id=FORTNITE_ID,
            outcome=CanonicalOfferDecisionType.REJECTED,
            ordinal=3,
        ),
        _decision(
            marketplace="ggsel",
            external_id="retired-confirmed",
            product_id=FORTNITE_ID,
            outcome=CanonicalOfferDecisionType.CONFIRMED,
            ordinal=4,
        ),
    )
    product_items = tuple(reversed(products)) if reverse else products
    offer_items = tuple(reversed(offers)) if reverse else offers
    decision_items = tuple(reversed(decisions)) if reverse else decisions
    for product in product_items:
        await provider.canonical_products.save(product)
    for offer in offer_items:
        await provider.offers.save(TENANT_ID, offer)
    for decision in decision_items:
        await provider.canonical_offer_decisions.append(decision)

    state = await provider.offers.get_availability_state(
        TENANT_ID,
        "ggsel",
        "retired-confirmed",
    )
    assert state is not None
    result = await provider.offers.set_availability_status(
        TENANT_ID,
        "ggsel",
        "retired-confirmed",
        OfferAvailabilityStatus.RETIRED,
        DECIDED_AT,
        state.version,
    )
    assert result.outcome is StateTransitionOutcome.APPLIED


def _minecraft_product() -> CanonicalProduct:
    return CanonicalProduct(
        id=MINECRAFT_ID,
        tenant_id=TENANT_ID,
        name="Minecraft",
        category="Games",
        aliases=("minecraft java", "minecraft bedrock"),
    )


def _fortnite_product() -> CanonicalProduct:
    return CanonicalProduct(
        id=FORTNITE_ID,
        tenant_id=TENANT_ID,
        name="Fortnite",
        category="Games",
        aliases=("fortnite v-bucks",),
    )


def _offer(
    *,
    marketplace: str,
    external_id: str,
    canonical_product_id: UUID | None,
    tenant_id: UUID = TENANT_ID,
) -> ParsedOffer:
    normalized_marketplace = marketplace.strip().lower()
    return ParsedOffer(
        tenant_id=tenant_id,
        marketplace=marketplace,
        external_id=external_id,
        title=f"{normalized_marketplace} {external_id}",
        url=f"https://example.test/{normalized_marketplace}/{external_id}",
        price=Decimal("790.00"),
        currency="RUB",
        seller_id="seller-1",
        seller_name="Verified seller",
        source_category_id="minecraft",
        source_category_name="Minecraft",
        catalog_hub_code="minecraft",
        catalog_section_code="keys",
        canonical_product_id=canonical_product_id,
    )


def _decision(
    *,
    marketplace: str,
    external_id: str,
    product_id: UUID,
    outcome: CanonicalOfferDecisionType,
    ordinal: int,
    tenant_id: UUID = TENANT_ID,
) -> CanonicalOfferDecision:
    identity = (
        f"{tenant_id}:{marketplace}:{external_id}:{product_id}:{outcome}:{ordinal}"
    )
    return CanonicalOfferDecision(
        id=uuid5(NAMESPACE_URL, identity),
        tenant_id=tenant_id,
        marketplace=marketplace,
        external_id=external_id,
        canonical_product_id=product_id,
        decision=outcome,
        actor_id="catalog-reviewer",
        actor_type=AdminActorType.USER,
        request_id=f"request-{ordinal}",
        idempotency_key=f"decision-{ordinal}-{external_id}",
        request_fingerprint=sha256(identity.encode()).hexdigest(),
        created_at=DECIDED_AT.replace(minute=ordinal),
        reason="Reviewed for bounded catalog launch",
    )


async def _repository_state(
    provider: RepositoryProvider,
    tenant_id: UUID,
) -> tuple[object, object, object]:
    return (
        tuple(await provider.offers.list_by_tenant(tenant_id)),
        tuple(await provider.canonical_products.list_by_tenant(tenant_id)),
        tuple(await provider.canonical_offer_decisions.list_by_tenant(tenant_id)),
    )
