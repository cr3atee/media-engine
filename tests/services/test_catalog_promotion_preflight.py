from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import NAMESPACE_URL, UUID, uuid5

from app.domain.admin_actions import AdminActorType
from app.domain.canonical_offer_decisions import (
    CanonicalOfferDecision,
    CanonicalOfferDecisionType,
)
from app.domain.offer_availability import OfferAvailabilityStatus
from app.domain.processing import StateTransitionOutcome
from app.domain.tenancy import Tenant
from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer
from app.repositories.provider import RepositoryProvider, create_memory_provider
from app.services.catalog_promotion_manifest import (
    CatalogPromotionManifest,
    CatalogPromotionManifestService,
)
from app.services.catalog_promotion_preflight import (
    CatalogPromotionIssueCode,
    CatalogPromotionLinkActionType,
    CatalogPromotionPreflightResult,
    CatalogPromotionPreflightService,
    CatalogPromotionPreflightStatus,
    CatalogPromotionProductActionType,
)
from app.services.repository_scope import create_memory_repository_scope

SOURCE_TENANT_ID = UUID("76000000-0000-4000-8000-000000000001")
TARGET_TENANT_ID = UUID("76000000-0000-4000-8000-000000000002")
FOREIGN_TENANT_ID = UUID("76000000-0000-4000-8000-000000000003")
PRODUCT_ID = UUID("76000000-0000-4000-8000-000000000010")
OTHER_PRODUCT_ID = UUID("76000000-0000-4000-8000-000000000011")
NOW = datetime(2026, 11, 5, 8, 0, tzinfo=UTC)


def test_preflight_returns_ready_plan_without_mutating_target() -> None:
    async def scenario() -> None:
        manifest = await _manifest()
        target = create_memory_provider()
        await target.tenants.create(_tenant(TARGET_TENANT_ID))
        await target.offers.save(TARGET_TENANT_ID, _target_offer())
        before = await _target_state(target)

        result = await _service(target).inspect(
            manifest,
            target_tenant_id=TARGET_TENANT_ID,
        )

        assert result.status is CatalogPromotionPreflightStatus.READY
        assert result.required_mutations == 2
        assert result.issues == ()
        assert (
            result.product_actions[0].action is CatalogPromotionProductActionType.CREATE
        )
        assert result.link_actions[0].action is CatalogPromotionLinkActionType.LINK
        assert await _target_state(target) == before

    asyncio.run(scenario())


def test_preflight_reports_idempotent_no_changes() -> None:
    async def scenario() -> None:
        manifest = await _manifest()
        target = create_memory_provider()
        await target.tenants.create(_tenant(TARGET_TENANT_ID))
        await target.canonical_products.save(_target_product())
        await target.offers.save(
            TARGET_TENANT_ID,
            _target_offer(canonical_product_id=PRODUCT_ID),
        )

        result = await _service(target).inspect(
            manifest,
            target_tenant_id=TARGET_TENANT_ID,
        )

        assert result.status is CatalogPromotionPreflightStatus.NO_CHANGES
        assert result.required_mutations == 0
        assert (
            result.product_actions[0].action is CatalogPromotionProductActionType.REUSE
        )
        assert result.link_actions[0].action is CatalogPromotionLinkActionType.REUSE

    asyncio.run(scenario())


def test_preflight_requires_fresh_target_source_evidence() -> None:
    async def scenario() -> None:
        manifest = await _manifest()
        target = create_memory_provider()
        await target.tenants.create(_tenant(TARGET_TENANT_ID))

        result = await _service(target).inspect(
            manifest,
            target_tenant_id=TARGET_TENANT_ID,
        )

        assert result.status is CatalogPromotionPreflightStatus.BLOCKED
        assert result.required_mutations == 1
        assert _issue_codes(result) == {
            CatalogPromotionIssueCode.SOURCE_REFRESH_REQUIRED
        }

    asyncio.run(scenario())


def test_preflight_blocks_invalid_manifest_and_tenant_states() -> None:
    async def scenario() -> None:
        manifest = await _manifest()
        tampered = replace(
            manifest,
            summary=replace(
                manifest.summary,
                promoted_links=manifest.summary.promoted_links + 1,
            ),
        )
        target = create_memory_provider()

        invalid = await _service(target).inspect(
            tampered,
            target_tenant_id=TARGET_TENANT_ID,
        )
        missing = await _service(target).inspect(
            manifest,
            target_tenant_id=TARGET_TENANT_ID,
        )
        await target.tenants.create(_tenant(TARGET_TENANT_ID, is_active=False))
        inactive = await _service(target).inspect(
            manifest,
            target_tenant_id=TARGET_TENANT_ID,
        )

        assert _issue_codes(invalid) == {CatalogPromotionIssueCode.INVALID_MANIFEST}
        assert invalid.product_actions == ()
        assert invalid.link_actions == ()
        assert CatalogPromotionIssueCode.TARGET_TENANT_NOT_FOUND in _issue_codes(
            missing
        )
        assert CatalogPromotionIssueCode.TARGET_TENANT_INACTIVE in _issue_codes(
            inactive
        )

    asyncio.run(scenario())


def test_preflight_reports_product_ownership_and_definition_conflicts() -> None:
    async def scenario() -> None:
        manifest = await _manifest()

        foreign_target = create_memory_provider()
        await foreign_target.tenants.create(_tenant(TARGET_TENANT_ID))
        await foreign_target.tenants.create(_tenant(FOREIGN_TENANT_ID))
        await foreign_target.canonical_products.save(
            replace(_target_product(), tenant_id=FOREIGN_TENANT_ID)
        )
        await foreign_target.offers.save(TARGET_TENANT_ID, _target_offer())
        foreign_result = await _service(foreign_target).inspect(
            manifest,
            target_tenant_id=TARGET_TENANT_ID,
        )

        changed_target = create_memory_provider()
        await changed_target.tenants.create(_tenant(TARGET_TENANT_ID))
        await changed_target.canonical_products.save(
            replace(_target_product(), name="Changed product")
        )
        await changed_target.offers.save(TARGET_TENANT_ID, _target_offer())
        changed_result = await _service(changed_target).inspect(
            manifest,
            target_tenant_id=TARGET_TENANT_ID,
        )

        assert CatalogPromotionIssueCode.PRODUCT_OWNED_BY_OTHER_TENANT in _issue_codes(
            foreign_result
        )
        assert CatalogPromotionIssueCode.PRODUCT_DEFINITION_CONFLICT in _issue_codes(
            changed_result
        )

    asyncio.run(scenario())


def test_preflight_reports_source_link_and_retirement_conflicts() -> None:
    async def scenario() -> None:
        manifest = await _manifest()

        drifted = await _target_with_product()
        await drifted.offers.save(
            TARGET_TENANT_ID,
            replace(_target_offer(), title="Changed source title"),
        )
        drifted_result = await _service(drifted).inspect(
            manifest,
            target_tenant_id=TARGET_TENANT_ID,
        )

        linked = await _target_with_product()
        await linked.canonical_products.save(
            CanonicalProduct(
                id=OTHER_PRODUCT_ID,
                tenant_id=TARGET_TENANT_ID,
                name="Other",
                category="Games",
                aliases=(),
            )
        )
        await linked.offers.save(
            TARGET_TENANT_ID,
            _target_offer(canonical_product_id=OTHER_PRODUCT_ID),
        )
        linked_result = await _service(linked).inspect(
            manifest,
            target_tenant_id=TARGET_TENANT_ID,
        )

        retired = await _target_with_product()
        await retired.offers.save(TARGET_TENANT_ID, _target_offer())
        state = await retired.offers.get_availability_state(
            TARGET_TENANT_ID,
            "ggsel",
            "offer-1",
        )
        assert state is not None
        transition = await retired.offers.set_availability_status(
            TARGET_TENANT_ID,
            "ggsel",
            "offer-1",
            OfferAvailabilityStatus.RETIRED,
            NOW,
            state.version,
        )
        assert transition.outcome is StateTransitionOutcome.APPLIED
        retired_result = await _service(retired).inspect(
            manifest,
            target_tenant_id=TARGET_TENANT_ID,
        )

        assert CatalogPromotionIssueCode.SOURCE_EVIDENCE_MISMATCH in _issue_codes(
            drifted_result
        )
        assert CatalogPromotionIssueCode.OFFER_LINK_CONFLICT in _issue_codes(
            linked_result
        )
        assert CatalogPromotionIssueCode.OFFER_RETIRED in _issue_codes(retired_result)

    asyncio.run(scenario())


async def _manifest() -> CatalogPromotionManifest:
    provider = create_memory_provider()
    product = CanonicalProduct(
        id=PRODUCT_ID,
        tenant_id=SOURCE_TENANT_ID,
        name="Minecraft",
        category="Games",
        aliases=("minecraft java",),
    )
    offer = ParsedOffer(
        tenant_id=SOURCE_TENANT_ID,
        marketplace="ggsel",
        external_id="offer-1",
        title="Minecraft Java",
        url="https://example.test/ggsel/offer-1",
        price=Decimal("790.00"),
        currency="RUB",
        source_category_id="66568",
        source_category_name="Minecraft",
        catalog_hub_code="minecraft",
        catalog_section_code="keys",
        canonical_product_id=PRODUCT_ID,
    )
    await provider.canonical_products.save(product)
    await provider.offers.save(SOURCE_TENANT_ID, offer)
    identity = f"{SOURCE_TENANT_ID}:ggsel:offer-1:{PRODUCT_ID}"
    await provider.canonical_offer_decisions.append(
        CanonicalOfferDecision(
            id=uuid5(NAMESPACE_URL, identity),
            tenant_id=SOURCE_TENANT_ID,
            marketplace="ggsel",
            external_id="offer-1",
            canonical_product_id=PRODUCT_ID,
            decision=CanonicalOfferDecisionType.CONFIRMED,
            actor_id="reviewer",
            actor_type=AdminActorType.USER,
            request_id="request-1",
            idempotency_key="decision-1",
            request_fingerprint=sha256(identity.encode("utf-8")).hexdigest(),
            created_at=NOW,
            reason="Reviewed",
        )
    )
    return await CatalogPromotionManifestService(
        create_memory_repository_scope(provider)
    ).build(SOURCE_TENANT_ID)


def _service(provider: RepositoryProvider) -> CatalogPromotionPreflightService:
    return CatalogPromotionPreflightService(create_memory_repository_scope(provider))


def _tenant(tenant_id: UUID, *, is_active: bool = True) -> Tenant:
    return Tenant(
        id=tenant_id,
        name=f"Tenant {tenant_id}",
        slug=f"tenant-{tenant_id.hex[-8:]}",
        is_active=is_active,
        created_at=NOW,
        updated_at=NOW,
    )


def _target_product() -> CanonicalProduct:
    return CanonicalProduct(
        id=PRODUCT_ID,
        tenant_id=TARGET_TENANT_ID,
        name="Minecraft",
        category="Games",
        aliases=("minecraft java",),
    )


def _target_offer(*, canonical_product_id: UUID | None = None) -> ParsedOffer:
    return ParsedOffer(
        tenant_id=TARGET_TENANT_ID,
        marketplace="ggsel",
        external_id="offer-1",
        title="Minecraft Java",
        url="https://example.test/ggsel/offer-1",
        price=Decimal("810.00"),
        currency="RUB",
        source_category_id="66568",
        source_category_name="Minecraft",
        catalog_hub_code="minecraft",
        catalog_section_code="keys",
        canonical_product_id=canonical_product_id,
    )


async def _target_with_product() -> RepositoryProvider:
    provider = create_memory_provider()
    await provider.tenants.create(_tenant(TARGET_TENANT_ID))
    await provider.canonical_products.save(_target_product())
    return provider


async def _target_state(provider: RepositoryProvider) -> tuple[object, object, object]:
    return (
        await provider.tenants.get_by_id(TARGET_TENANT_ID),
        tuple(await provider.canonical_products.list_by_tenant(TARGET_TENANT_ID)),
        tuple(await provider.offers.list_by_tenant(TARGET_TENANT_ID)),
    )


def _issue_codes(
    result: CatalogPromotionPreflightResult,
) -> set[CatalogPromotionIssueCode]:
    return {issue.code for issue in result.issues}
