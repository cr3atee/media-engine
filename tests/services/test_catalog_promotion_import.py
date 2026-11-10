from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from app.domain.admin_actions import AdminAction, AdminActorType, AdminResourceType
from app.domain.canonical_offer_decisions import (
    CanonicalOfferDecision,
    CanonicalOfferDecisionType,
)
from app.domain.tenancy import Tenant
from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer
from app.repositories.memory.memory_admin_actions import MemoryAdminActionRepository
from app.repositories.provider import RepositoryProvider, create_memory_provider
from app.services.admin_mutations import AdminCommandContext
from app.services.catalog_promotion_import import (
    CatalogPromotionImportCommand,
    CatalogPromotionImportError,
    CatalogPromotionImportService,
    catalog_promotion_approval_phrase,
    catalog_promotion_resource_id,
)
from app.services.catalog_promotion_manifest import (
    CatalogPromotionManifest,
    CatalogPromotionManifestService,
)
from app.services.catalog_promotion_preflight import (
    CatalogPromotionPreflightResult,
    CatalogPromotionPreflightService,
    CatalogPromotionPreflightStatus,
)
from app.services.repository_scope import create_memory_repository_scope

SOURCE_TENANT_ID = UUID("77000000-0000-4000-8000-000000000001")
TARGET_TENANT_ID = UUID("77000000-0000-4000-8000-000000000002")
PRODUCT_ID = UUID("77000000-0000-4000-8000-000000000010")
ACTION_ID = UUID("77000000-0000-4000-8000-000000000020")
NOW = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)


def test_import_applies_atomically_and_replays_by_idempotency_key() -> None:
    async def scenario() -> None:
        manifest = await _manifest()
        target = await _target()
        preflight = await _preflight(target, manifest)
        service = _service(target)
        command = _command(manifest, preflight)

        applied = await service.apply(command)
        replayed = await service.apply(command)

        assert applied.action_id == ACTION_ID
        assert applied.products_created == 1
        assert applied.links_created == 1
        assert not applied.replayed
        assert replayed == replace(applied, replayed=True)
        product = await target.canonical_products.get_by_tenant_and_id(
            TARGET_TENANT_ID,
            PRODUCT_ID,
        )
        offer = await target.offers.get_by_identity(
            TARGET_TENANT_ID,
            "ggsel",
            "offer-1",
        )
        assert product is not None
        assert offer is not None and offer.canonical_product_id == PRODUCT_ID
        audit = await target.admin_actions.list_for_resource(
            AdminResourceType.CATALOG_PROMOTION,
            catalog_promotion_resource_id(TARGET_TENANT_ID, manifest.digest),
        )
        assert len(audit) == 1
        assert audit[0].tenant_id == TARGET_TENANT_ID
        assert dict(audit[0].metadata)["manifest_digest"] == manifest.digest

    asyncio.run(scenario())


def test_import_requires_exact_approval_and_ready_plan() -> None:
    async def scenario() -> None:
        manifest = await _manifest()
        target = await _target()
        preflight = await _preflight(target, manifest)
        service = _service(target)

        with pytest.raises(CatalogPromotionImportError) as approval_error:
            await service.apply(
                replace(_command(manifest, preflight), approval_phrase="approve")
            )
        assert approval_error.value.code == "approval_required"

        blocked = replace(preflight, status=CatalogPromotionPreflightStatus.BLOCKED)
        with pytest.raises(CatalogPromotionImportError) as plan_error:
            await service.apply(_command(manifest, blocked))
        assert plan_error.value.code == "preflight_not_ready"
        assert await target.canonical_products.get_by_id(PRODUCT_ID) is None

    asyncio.run(scenario())


def test_import_rejects_preflight_drift_and_idempotency_conflict() -> None:
    async def scenario() -> None:
        manifest = await _manifest()
        target = await _target()
        preflight = await _preflight(target, manifest)
        service = _service(target)
        command = _command(manifest, preflight)

        await target.offers.save(
            TARGET_TENANT_ID,
            replace(_target_offer(), title="Changed after preflight"),
        )
        with pytest.raises(CatalogPromotionImportError) as drift_error:
            await service.apply(command)
        assert drift_error.value.code == "preflight_drift"

        await target.offers.save(TARGET_TENANT_ID, _target_offer())
        refreshed = await _preflight(target, manifest)
        accepted = _command(manifest, refreshed)
        await service.apply(accepted)
        with pytest.raises(CatalogPromotionImportError) as conflict_error:
            await service.apply(replace(accepted, reason="Different reason"))
        assert conflict_error.value.code == "idempotency_conflict"

    asyncio.run(scenario())


def test_import_rolls_back_products_links_and_audit_together() -> None:
    async def scenario() -> None:
        manifest = await _manifest()
        target = await _target()
        preflight = await _preflight(target, manifest)
        target.admin_actions = _FailingAdminActionRepository()
        before = await _state(target, manifest.digest)

        with pytest.raises(RuntimeError, match="forced audit failure"):
            await _service(target).apply(_command(manifest, preflight))

        assert await _state(target, manifest.digest) == before
        assert await target.canonical_products.get_by_id(PRODUCT_ID) is None
        offer = await target.offers.get_by_identity(
            TARGET_TENANT_ID,
            "ggsel",
            "offer-1",
        )
        assert offer is not None and offer.canonical_product_id is None

    asyncio.run(scenario())


def test_import_rejects_manifest_and_tenant_context_mismatch() -> None:
    async def scenario() -> None:
        manifest = await _manifest()
        target = await _target()
        preflight = await _preflight(target, manifest)
        service = _service(target)
        mismatched_manifest = replace(manifest, digest="f" * 64)

        with pytest.raises(CatalogPromotionImportError) as manifest_error:
            await service.apply(_command(mismatched_manifest, preflight))
        assert manifest_error.value.code == "manifest_mismatch"

        wrong_context = replace(
            _command(manifest, preflight),
            context=replace(_context(), tenant_id=SOURCE_TENANT_ID),
        )
        with pytest.raises(CatalogPromotionImportError) as tenant_error:
            await service.apply(wrong_context)
        assert tenant_error.value.code == "tenant_context_mismatch"

    asyncio.run(scenario())


class _FailingAdminActionRepository(MemoryAdminActionRepository):
    async def append(self, action: AdminAction) -> AdminAction:
        del action
        raise RuntimeError("forced audit failure")


async def _manifest() -> CatalogPromotionManifest:
    source = create_memory_provider()
    product = CanonicalProduct(
        id=PRODUCT_ID,
        tenant_id=SOURCE_TENANT_ID,
        name="Minecraft",
        category="Games",
        aliases=("minecraft java",),
    )
    offer = replace(
        _target_offer(),
        tenant_id=SOURCE_TENANT_ID,
        canonical_product_id=PRODUCT_ID,
    )
    await source.canonical_products.save(product)
    await source.offers.save(SOURCE_TENANT_ID, offer)
    identity = f"{SOURCE_TENANT_ID}:ggsel:offer-1:{PRODUCT_ID}"
    await source.canonical_offer_decisions.append(
        CanonicalOfferDecision(
            id=uuid5(NAMESPACE_URL, identity),
            tenant_id=SOURCE_TENANT_ID,
            marketplace="ggsel",
            external_id="offer-1",
            canonical_product_id=PRODUCT_ID,
            decision=CanonicalOfferDecisionType.CONFIRMED,
            actor_id="reviewer",
            actor_type=AdminActorType.USER,
            request_id="review-request",
            idempotency_key="review-decision",
            request_fingerprint=sha256(identity.encode("utf-8")).hexdigest(),
            created_at=NOW,
            reason="Reviewed",
        )
    )
    return await CatalogPromotionManifestService(
        create_memory_repository_scope(source)
    ).build(SOURCE_TENANT_ID)


async def _target() -> RepositoryProvider:
    target = create_memory_provider()
    await target.tenants.create(
        Tenant(
            id=TARGET_TENANT_ID,
            name="Promotion target",
            slug="promotion-target",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await target.offers.save(TARGET_TENANT_ID, _target_offer())
    return target


def _target_offer() -> ParsedOffer:
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
    )


async def _preflight(
    target: RepositoryProvider,
    manifest: CatalogPromotionManifest,
) -> CatalogPromotionPreflightResult:
    return await CatalogPromotionPreflightService(
        create_memory_repository_scope(target)
    ).inspect(manifest, target_tenant_id=TARGET_TENANT_ID)


def _service(target: RepositoryProvider) -> CatalogPromotionImportService:
    return CatalogPromotionImportService(
        create_memory_repository_scope(target),
        clock=lambda: NOW,
        action_id_factory=lambda: ACTION_ID,
    )


def _context() -> AdminCommandContext:
    return AdminCommandContext(
        tenant_id=TARGET_TENANT_ID,
        actor_id="catalog-operator",
        actor_type=AdminActorType.USER,
        request_id="import-request",
        idempotency_key="catalog-import-1",
    )


def _command(
    manifest: CatalogPromotionManifest,
    preflight: CatalogPromotionPreflightResult,
) -> CatalogPromotionImportCommand:
    return CatalogPromotionImportCommand(
        manifest=manifest,
        preflight=preflight,
        approval_phrase=catalog_promotion_approval_phrase(
            manifest,
            preflight.target_tenant_id,
        ),
        context=_context(),
        reason="Promote reviewed launch catalog",
    )


async def _state(
    provider: RepositoryProvider,
    manifest_digest: str,
) -> tuple[object, object, object]:
    return (
        tuple(await provider.canonical_products.list_by_tenant(TARGET_TENANT_ID)),
        tuple(await provider.offers.list_by_tenant(TARGET_TENANT_ID)),
        tuple(
            await provider.admin_actions.list_for_resource(
                AdminResourceType.CATALOG_PROMOTION,
                catalog_promotion_resource_id(TARGET_TENANT_ID, manifest_digest),
            )
        ),
    )
