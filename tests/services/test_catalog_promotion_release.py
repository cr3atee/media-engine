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
from app.domain.tenancy import Tenant
from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer
from app.repositories.provider import RepositoryProvider, create_memory_provider
from app.services.admin_mutations import AdminCommandContext
from app.services.catalog_promotion_preflight import CatalogPromotionPreflightStatus
from app.services.catalog_promotion_release import (
    CatalogPromotionReleaseError,
    CatalogPromotionReleaseService,
)
from app.services.repository_scope import create_memory_repository_scope

SOURCE_TENANT_ID = UUID("78000000-0000-4000-8000-000000000001")
TARGET_TENANT_ID = UUID("78000000-0000-4000-8000-000000000002")
PRODUCT_ID = UUID("78000000-0000-4000-8000-000000000010")
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def test_release_preview_apply_and_restart_replay() -> None:
    async def scenario() -> None:
        source, target = await _providers()
        service = _service(source, target)
        source_before = await _state(source, SOURCE_TENANT_ID)
        target_before = await _state(target, TARGET_TENANT_ID)

        preview = await service.preview(
            source_tenant_id=SOURCE_TENANT_ID,
            target_tenant_id=TARGET_TENANT_ID,
        )

        assert preview.preflight.status is CatalogPromotionPreflightStatus.READY
        assert await _state(source, SOURCE_TENANT_ID) == source_before
        assert await _state(target, TARGET_TENANT_ID) == target_before

        context = _context()
        applied = await service.apply(
            preview,
            approval_phrase=preview.approval_phrase,
            context=context,
            reason="Release reviewed catalog",
        )
        assert applied.verified
        assert not applied.imported.replayed

        restarted = _service(source, target)
        replay_preview = await restarted.preview(
            source_tenant_id=SOURCE_TENANT_ID,
            target_tenant_id=TARGET_TENANT_ID,
        )
        replayed = await restarted.apply(
            replay_preview,
            approval_phrase=replay_preview.approval_phrase,
            context=context,
            reason="Release reviewed catalog",
        )
        assert (
            replay_preview.preflight.status
            is CatalogPromotionPreflightStatus.NO_CHANGES
        )
        assert replayed.verified
        assert replayed.imported.replayed
        assert replayed.imported.action_id == applied.imported.action_id

    asyncio.run(scenario())


def test_release_fails_closed_for_blocked_or_unapproved_commands() -> None:
    async def scenario() -> None:
        source, target = await _providers()
        service = _service(source, target)
        ready = await service.preview(
            source_tenant_id=SOURCE_TENANT_ID,
            target_tenant_id=TARGET_TENANT_ID,
        )

        with pytest.raises(CatalogPromotionReleaseError) as approval_error:
            await service.apply(
                ready,
                approval_phrase="approve",
                context=_context(),
                reason="Release reviewed catalog",
            )
        assert approval_error.value.code == "approval_required"

        await target.offers.save(
            TARGET_TENANT_ID,
            replace(_offer(TARGET_TENANT_ID, None), title="Changed evidence"),
        )
        blocked = await service.preview(
            source_tenant_id=SOURCE_TENANT_ID,
            target_tenant_id=TARGET_TENANT_ID,
        )
        assert blocked.preflight.status is CatalogPromotionPreflightStatus.BLOCKED
        with pytest.raises(CatalogPromotionReleaseError) as blocked_error:
            await service.apply(
                blocked,
                approval_phrase=blocked.approval_phrase,
                context=_context(),
                reason="Release reviewed catalog",
            )
        assert blocked_error.value.code == "preflight_blocked"

    asyncio.run(scenario())


def test_release_replay_requires_the_original_command_identity() -> None:
    async def scenario() -> None:
        source, target = await _providers()
        service = _service(source, target)
        preview = await service.preview(
            source_tenant_id=SOURCE_TENANT_ID,
            target_tenant_id=TARGET_TENANT_ID,
        )
        await service.apply(
            preview,
            approval_phrase=preview.approval_phrase,
            context=_context(),
            reason="Release reviewed catalog",
        )
        completed = await service.preview(
            source_tenant_id=SOURCE_TENANT_ID,
            target_tenant_id=TARGET_TENANT_ID,
        )

        with pytest.raises(CatalogPromotionReleaseError) as replay_error:
            await service.apply(
                completed,
                approval_phrase=completed.approval_phrase,
                context=replace(
                    _context(),
                    idempotency_key="catalog-release-other",
                ),
                reason="Release reviewed catalog",
            )
        assert replay_error.value.code == "replay_not_found"

    asyncio.run(scenario())


async def _providers() -> tuple[RepositoryProvider, RepositoryProvider]:
    source = create_memory_provider()
    target = create_memory_provider()
    await source.tenants.create(_tenant(SOURCE_TENANT_ID, "Source", "source"))
    await target.tenants.create(_tenant(TARGET_TENANT_ID, "Target", "target"))
    product = CanonicalProduct(
        id=PRODUCT_ID,
        tenant_id=SOURCE_TENANT_ID,
        name="Minecraft",
        category="Games",
        aliases=("minecraft java",),
    )
    source_offer = _offer(SOURCE_TENANT_ID, PRODUCT_ID)
    await source.canonical_products.save(product)
    await source.offers.save(SOURCE_TENANT_ID, source_offer)
    identity = f"{SOURCE_TENANT_ID}:ggsel:release-offer:{PRODUCT_ID}"
    await source.canonical_offer_decisions.append(
        CanonicalOfferDecision(
            id=uuid5(NAMESPACE_URL, identity),
            tenant_id=SOURCE_TENANT_ID,
            marketplace="ggsel",
            external_id="release-offer",
            canonical_product_id=PRODUCT_ID,
            decision=CanonicalOfferDecisionType.CONFIRMED,
            actor_id="reviewer",
            actor_type=AdminActorType.USER,
            request_id="review-request",
            idempotency_key="review-release-offer",
            request_fingerprint=sha256(identity.encode("utf-8")).hexdigest(),
            created_at=NOW,
            reason="Reviewed",
        )
    )
    await target.offers.save(TARGET_TENANT_ID, _offer(TARGET_TENANT_ID, None))
    return source, target


def _service(
    source: RepositoryProvider,
    target: RepositoryProvider,
) -> CatalogPromotionReleaseService:
    return CatalogPromotionReleaseService(
        create_memory_repository_scope(source),
        create_memory_repository_scope(target),
    )


def _context() -> AdminCommandContext:
    return AdminCommandContext(
        tenant_id=TARGET_TENANT_ID,
        actor_id="release-operator",
        actor_type=AdminActorType.PLATFORM_ADMIN,
        elevated=True,
        request_id="catalog-release-request",
        idempotency_key="catalog-release-1",
    )


def _offer(tenant_id: UUID, product_id: UUID | None) -> ParsedOffer:
    return ParsedOffer(
        tenant_id=tenant_id,
        marketplace="ggsel",
        external_id="release-offer",
        title="Minecraft Java",
        url="https://example.test/ggsel/release-offer",
        price=Decimal("790.00"),
        currency="RUB",
        source_category_id="66568",
        source_category_name="Minecraft",
        canonical_product_id=product_id,
    )


def _tenant(tenant_id: UUID, name: str, slug: str) -> Tenant:
    return Tenant(
        id=tenant_id,
        name=name,
        slug=slug,
        created_at=NOW,
        updated_at=NOW,
    )


async def _state(
    provider: RepositoryProvider,
    tenant_id: UUID,
) -> tuple[object, object, object]:
    return (
        tuple(await provider.canonical_products.list_by_tenant(tenant_id)),
        tuple(await provider.offers.list_by_tenant(tenant_id)),
        tuple(await provider.canonical_offer_decisions.list_by_tenant(tenant_id)),
    )
