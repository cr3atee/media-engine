from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.domain.admin_actions import AdminActorType
from app.domain.canonical_offer_decisions import CanonicalOfferDecisionType
from app.matching.confidence import MatchDecision
from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer
from app.repositories.provider import RepositoryProvider, create_memory_provider
from app.services.canonical_offer_review import (
    CanonicalOfferReviewContext,
    CanonicalOfferReviewService,
    ReviewCanonicalOfferCommand,
)
from app.services.canonical_offer_review_queue import (
    CanonicalOfferReviewQueueService,
)
from app.services.repository_scope import create_memory_repository_scope

TENANT_A_ID = UUID("39000000-0000-4000-8000-000000001001")
TENANT_B_ID = UUID("39000000-0000-4000-8000-000000001002")
PRODUCT_A_ID = UUID("39000000-0000-4000-8000-000000002001")
PRODUCT_B_ID = UUID("39000000-0000-4000-8000-000000002002")
NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run one queue scenario without an async pytest plugin."""
    return asyncio.run(awaitable)


def test_queue_contains_only_tenant_review_confidence_candidates() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        await provider.canonical_products.save(_product())
        await provider.canonical_products.save(
            _product(
                tenant_id=TENANT_B_ID,
                product_id=PRODUCT_B_ID,
                name="Foreign Tenant Product",
            )
        )
        await provider.offers.save(
            TENANT_A_ID,
            _offer(external_id="review", title=_review_title()),
        )
        await provider.offers.save(
            TENANT_A_ID,
            _offer(
                external_id="auto",
                title="Minecraft Java Bedrock Windows",
            ),
        )
        await provider.offers.save(
            TENANT_A_ID,
            _offer(external_id="none", title="Completely Different Product"),
        )

        candidates = await _queue(provider).list_candidates(TENANT_A_ID)

        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.offer.external_id == "review"
        assert candidate.canonical_product.id == PRODUCT_A_ID
        assert candidate.similarity == 0.8
        assert candidate.match_decision is MatchDecision.REVIEW

    run_async(scenario())


def test_terminal_pair_is_excluded_before_selecting_next_best_candidate() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        await provider.canonical_products.save(_product())
        await provider.canonical_products.save(
            _product(
                product_id=PRODUCT_B_ID,
                name="Minecraft Java Bedrock Premium",
            )
        )
        await provider.offers.save(
            TENANT_A_ID,
            _offer(external_id="review", title=_review_title()),
        )
        scope = create_memory_repository_scope(provider)
        review = CanonicalOfferReviewService(
            scope,
            clock=lambda: NOW,
            decision_id_factory=lambda: UUID("39000000-0000-4000-8000-000000003001"),
        )
        await review.review(
            ReviewCanonicalOfferCommand(
                tenant_id=TENANT_A_ID,
                marketplace="ggsel",
                external_id="review",
                canonical_product_id=PRODUCT_A_ID,
                decision=CanonicalOfferDecisionType.REJECTED,
                reason="Different package",
            ),
            CanonicalOfferReviewContext(
                actor_id="reviewer-1",
                actor_type=AdminActorType.USER,
                request_id="request-1",
                idempotency_key="reject-product-a",
            ),
        )

        candidates = await CanonicalOfferReviewQueueService(scope).list_candidates(
            TENANT_A_ID
        )

        assert len(candidates) == 1
        assert candidates[0].canonical_product.id == PRODUCT_B_ID
        assert candidates[0].similarity == 0.8

    run_async(scenario())


def test_linked_and_incomplete_offers_are_not_review_candidates() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        await provider.canonical_products.save(_product())
        await provider.offers.save(
            TENANT_A_ID,
            _offer(
                external_id="linked",
                title=_review_title(),
                canonical_product_id=PRODUCT_A_ID,
            ),
        )
        await provider.offers.save(
            TENANT_A_ID,
            _offer(external_id="untitled", title=None),
        )
        await provider.offers.save(
            TENANT_A_ID,
            _offer(external_id=None, title=_review_title()),
        )

        queue = _queue(provider)
        assert await queue.list_candidates(TENANT_A_ID) == ()
        assert await queue.list_product_proposals(TENANT_A_ID) == ()

    run_async(scenario())


def test_product_proposals_are_stable_and_tenant_scoped() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        await provider.canonical_products.save(_product())
        await provider.canonical_products.save(
            _product(
                tenant_id=TENANT_B_ID,
                product_id=PRODUCT_B_ID,
                name="Foreign Tenant Product",
            )
        )
        await provider.offers.save(
            TENANT_A_ID,
            _offer(
                external_id="proposal-a",
                title="  Stardew   Valley Complete  ",
            ),
        )
        await provider.offers.save(
            TENANT_B_ID,
            _offer(
                tenant_id=TENANT_B_ID,
                external_id="proposal-b",
                title="Hades Complete",
            ),
        )

        queue = _queue(provider)
        first = await queue.list_product_proposals(TENANT_A_ID)
        repeated = await queue.list_product_proposals(TENANT_A_ID)
        foreign = await queue.list_product_proposals(TENANT_B_ID)

        assert len(first) == 1
        assert first[0].proposal_id == repeated[0].proposal_id
        assert first[0].offer.external_id == "proposal-a"
        assert first[0].proposed_name == "Stardew Valley Complete"
        assert first[0].nearest_canonical_product is not None
        assert first[0].nearest_canonical_product.id == PRODUCT_A_ID
        assert first[0].similarity == 0.0
        assert len(foreign) == 1
        assert foreign[0].offer.external_id == "proposal-b"
        assert foreign[0].proposal_id != first[0].proposal_id

    run_async(scenario())


def test_terminal_pair_is_excluded_before_building_product_proposal() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        await provider.canonical_products.save(_product(name="Minecraft Dungeons"))
        await provider.canonical_products.save(
            _product(
                product_id=PRODUCT_B_ID,
                name="Minecraft Legends Standard Extra",
            )
        )
        await provider.offers.save(
            TENANT_A_ID,
            _offer(
                external_id="proposal",
                title="Minecraft Dungeons Deluxe",
            ),
        )
        scope = create_memory_repository_scope(provider)
        queue = CanonicalOfferReviewQueueService(scope)

        initial = await queue.list_product_proposals(TENANT_A_ID)
        assert len(initial) == 1
        assert initial[0].nearest_canonical_product is not None
        assert initial[0].nearest_canonical_product.id == PRODUCT_A_ID

        review = CanonicalOfferReviewService(
            scope,
            clock=lambda: NOW,
            decision_id_factory=lambda: UUID("39000000-0000-4000-8000-000000003002"),
        )
        await review.review(
            ReviewCanonicalOfferCommand(
                tenant_id=TENANT_A_ID,
                marketplace="ggsel",
                external_id="proposal",
                canonical_product_id=PRODUCT_A_ID,
                decision=CanonicalOfferDecisionType.REJECTED,
                reason="Different game",
            ),
            CanonicalOfferReviewContext(
                actor_id="reviewer-1",
                actor_type=AdminActorType.USER,
                request_id="request-2",
                idempotency_key="reject-proposal-product-a",
            ),
        )

        after_rejection = await queue.list_product_proposals(TENANT_A_ID)

        assert len(after_rejection) == 1
        assert after_rejection[0].proposal_id == initial[0].proposal_id
        assert after_rejection[0].nearest_canonical_product is not None
        assert after_rejection[0].nearest_canonical_product.id == PRODUCT_B_ID
        assert after_rejection[0].similarity < initial[0].similarity

    run_async(scenario())


def test_queue_uses_canonical_aliases_without_changing_thresholds() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        await provider.canonical_products.save(
            CanonicalProduct(
                id=PRODUCT_A_ID,
                tenant_id=TENANT_A_ID,
                name="Minecraft Complete Collection",
                category="Games",
                aliases=("Minecraft Java Bedrock Windows",),
            )
        )
        await provider.offers.save(
            TENANT_A_ID,
            _offer(external_id="alias-review", title=_review_title()),
        )

        candidates = await _queue(provider).list_candidates(TENANT_A_ID)

        assert len(candidates) == 1
        assert candidates[0].canonical_product.id == PRODUCT_A_ID
        assert candidates[0].similarity == 0.8
        assert candidates[0].match_decision is MatchDecision.REVIEW

    run_async(scenario())


def _queue(provider: RepositoryProvider) -> CanonicalOfferReviewQueueService:
    return CanonicalOfferReviewQueueService(create_memory_repository_scope(provider))


def _product(
    *,
    tenant_id: UUID = TENANT_A_ID,
    product_id: UUID = PRODUCT_A_ID,
    name: str = "Minecraft Java Bedrock Windows",
) -> CanonicalProduct:
    return CanonicalProduct(
        id=product_id,
        tenant_id=tenant_id,
        name=name,
        category="Games",
        aliases=(),
    )


def _offer(
    *,
    external_id: str | None,
    title: str | None,
    canonical_product_id: UUID | None = None,
    tenant_id: UUID = TENANT_A_ID,
) -> ParsedOffer:
    return ParsedOffer(
        tenant_id=tenant_id,
        marketplace="ggsel",
        external_id=external_id,
        title=title,
        url=(
            f"https://ggsel.net/catalog/product/{external_id}"
            if external_id is not None
            else None
        ),
        price=Decimal("790.00"),
        currency="RUB",
        canonical_product_id=canonical_product_id,
    )


def _review_title() -> str:
    return "Minecraft Java Bedrock Windows Premium"
