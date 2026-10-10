from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import UUID

from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer
from app.repositories.provider import create_memory_provider
from app.services.canonical_offer_review_queue import (
    CanonicalOfferReviewQueueService,
)
from app.services.repository_scope import create_memory_repository_scope

TENANT_ID = UUID("4a000000-0000-4000-8000-000000000001")
FOREIGN_TENANT_ID = UUID("4a000000-0000-4000-8000-000000000002")
PRODUCT_ID = UUID("4a000000-0000-4000-8000-000000000010")


def test_onboarding_summary_reports_complete_tenant_progress() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        product = CanonicalProduct(
            id=PRODUCT_ID,
            tenant_id=TENANT_ID,
            name="Minecraft Java Bedrock Windows",
            category="Games",
            aliases=(),
        )
        await provider.canonical_products.save(product)
        for offer in (
            _offer("ggsel", "linked", "Linked offer", product_id=PRODUCT_ID),
            _offer(
                "ggsel",
                "review",
                "Minecraft Java Bedrock Windows Premium",
            ),
            _offer("ggsel", "automatic", "Minecraft Java Bedrock Windows"),
            _offer("playerok", "proposal", "Stardew Valley Complete"),
        ):
            await provider.offers.save(TENANT_ID, offer)

        service = CanonicalOfferReviewQueueService(
            create_memory_repository_scope(provider)
        )
        summary = await service.get_onboarding_summary(TENANT_ID)
        workspace = await service.get_onboarding_workspace(TENANT_ID)
        foreign = await service.get_onboarding_summary(FOREIGN_TENANT_ID)

        assert summary.total_offers == 4
        assert summary.linked_offers == 1
        assert summary.unresolved_offers == 3
        assert summary.review_candidates == 1
        assert summary.product_proposals == 1
        assert summary.unqueued_offers == 1
        assert summary.canonical_products == 1
        assert summary.terminal_decisions == 0
        assert tuple(item.marketplace for item in summary.marketplaces) == (
            "ggsel",
            "playerok",
        )

        ggsel, playerok = summary.marketplaces
        assert (
            ggsel.total_offers,
            ggsel.linked_offers,
            ggsel.unresolved_offers,
            ggsel.review_candidates,
            ggsel.product_proposals,
            ggsel.unqueued_offers,
        ) == (3, 1, 2, 1, 0, 1)
        assert (
            playerok.total_offers,
            playerok.linked_offers,
            playerok.unresolved_offers,
            playerok.review_candidates,
            playerok.product_proposals,
            playerok.unqueued_offers,
        ) == (1, 0, 1, 0, 1, 0)
        assert foreign.total_offers == 0
        assert foreign.marketplaces == ()
        assert workspace.summary == summary
        assert len(workspace.review_candidates) == 1
        assert len(workspace.product_proposals) == 1

    asyncio.run(scenario())


def _offer(
    marketplace: str,
    external_id: str,
    title: str,
    *,
    product_id: UUID | None = None,
) -> ParsedOffer:
    return ParsedOffer(
        tenant_id=TENANT_ID,
        marketplace=marketplace,
        external_id=external_id,
        title=title,
        url=f"https://example.test/{marketplace}/{external_id}",
        price=Decimal("790.00"),
        currency="RUB",
        canonical_product_id=product_id,
    )
