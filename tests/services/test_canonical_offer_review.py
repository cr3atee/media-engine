from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from app.domain.admin_actions import AdminActorType
from app.domain.canonical_offer_decisions import (
    CanonicalOfferDecision,
    CanonicalOfferDecisionType,
)
from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer
from app.repositories.memory import MemoryCanonicalOfferDecisionRepository
from app.repositories.provider import RepositoryProvider, create_memory_provider
from app.services.canonical_offer_linking import CanonicalProductUnavailableError
from app.services.canonical_offer_review import (
    CanonicalOfferActiveLinkConflictError,
    CanonicalOfferDecisionConflictError,
    CanonicalOfferReviewContext,
    CanonicalOfferReviewIdempotencyConflictError,
    CanonicalOfferReviewService,
    ReviewCanonicalOfferCommand,
)
from app.services.repository_scope import create_memory_repository_scope

TENANT_A_ID = UUID("19000000-0000-4000-8000-000000001001")
TENANT_B_ID = UUID("19000000-0000-4000-8000-000000001002")
PRODUCT_A_ID = UUID("19000000-0000-4000-8000-000000002001")
DECISION_ID = UUID("19000000-0000-4000-8000-000000003001")
NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run one async review scenario without an async pytest plugin."""
    return asyncio.run(awaitable)


def test_confirm_is_atomic_audited_and_idempotent() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        product = _product()
        offer = _offer()
        await provider.canonical_products.save(product)
        await provider.offers.save(TENANT_A_ID, offer)
        service = _service(provider)
        command = _command(CanonicalOfferDecisionType.CONFIRMED)
        context = _context()

        result = await service.review(command, context)
        replay = await service.review(command, context)
        stored_offer = await provider.offers.get_by_identity(
            TENANT_A_ID,
            "ggsel",
            "offer-1",
        )
        decisions = await provider.canonical_offer_decisions.list_for_offer(
            TENANT_A_ID,
            "ggsel",
            "offer-1",
        )

        assert result.replayed is False
        assert result.decision.id == DECISION_ID
        assert result.decision.decision is CanonicalOfferDecisionType.CONFIRMED
        assert result.decision.actor_id == "reviewer-1"
        assert replay.replayed is True
        assert replay.decision == result.decision
        assert stored_offer is not None
        assert stored_offer.canonical_product_id == PRODUCT_A_ID
        assert tuple(decisions) == (result.decision,)

    run_async(scenario())


def test_reject_records_terminal_pair_without_mutating_offer() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        product = _product()
        offer = _offer()
        await provider.canonical_products.save(product)
        await provider.offers.save(TENANT_A_ID, offer)

        result = await _service(provider).review(
            _command(CanonicalOfferDecisionType.REJECTED),
            _context(),
        )
        stored_offer = await provider.offers.get_by_identity(
            TENANT_A_ID,
            "ggsel",
            "offer-1",
        )
        stored_decision = await provider.canonical_offer_decisions.get_for_pair(
            TENANT_A_ID,
            "ggsel",
            "offer-1",
            PRODUCT_A_ID,
        )

        assert result.decision.decision is CanonicalOfferDecisionType.REJECTED
        assert result.decision.reason == "not the same edition"
        assert stored_offer == offer
        assert stored_decision == result.decision

    run_async(scenario())


def test_reusing_idempotency_key_for_other_semantics_fails() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        await provider.canonical_products.save(_product())
        await provider.offers.save(TENANT_A_ID, _offer())
        service = _service(provider)
        context = _context()
        await service.review(
            _command(CanonicalOfferDecisionType.REJECTED),
            context,
        )

        with pytest.raises(CanonicalOfferReviewIdempotencyConflictError):
            await service.review(
                _command(CanonicalOfferDecisionType.CONFIRMED),
                context,
            )

        decisions = await provider.canonical_offer_decisions.list_for_offer(
            TENANT_A_ID,
            "ggsel",
            "offer-1",
        )
        assert len(decisions) == 1

    run_async(scenario())


def test_pair_cannot_receive_conflicting_terminal_decision() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        await provider.canonical_products.save(_product())
        await provider.offers.save(TENANT_A_ID, _offer())
        service = _service(provider)
        await service.review(
            _command(CanonicalOfferDecisionType.REJECTED),
            _context(),
        )

        with pytest.raises(CanonicalOfferDecisionConflictError):
            await service.review(
                _command(CanonicalOfferDecisionType.CONFIRMED),
                _context(idempotency_key="review-2"),
            )

        stored_offer = await provider.offers.get_by_identity(
            TENANT_A_ID,
            "ggsel",
            "offer-1",
        )
        assert stored_offer is not None
        assert stored_offer.canonical_product_id is None

    run_async(scenario())


def test_terminal_pair_requires_original_idempotency_key_for_replay() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        await provider.canonical_products.save(_product())
        await provider.offers.save(TENANT_A_ID, _offer())
        service = _service(provider)
        command = _command(CanonicalOfferDecisionType.REJECTED)
        await service.review(command, _context())

        with pytest.raises(CanonicalOfferDecisionConflictError):
            await service.review(
                command,
                _context(idempotency_key="review-new-key"),
            )

    run_async(scenario())


def test_cross_tenant_review_is_hidden_without_mutation() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        await provider.canonical_products.save(_product(tenant_id=TENANT_A_ID))
        foreign_offer = _offer(tenant_id=TENANT_B_ID)
        await provider.offers.save(TENANT_B_ID, foreign_offer)
        service = _service(provider)

        with pytest.raises(CanonicalProductUnavailableError):
            await service.review(
                _command(
                    CanonicalOfferDecisionType.CONFIRMED,
                    tenant_id=TENANT_B_ID,
                ),
                _context(),
            )

        assert (
            await provider.canonical_offer_decisions.list_for_offer(
                TENANT_B_ID,
                "ggsel",
                "offer-1",
            )
            == ()
        )
        assert (
            await provider.offers.get_by_identity(
                TENANT_B_ID,
                "ggsel",
                "offer-1",
            )
            == foreign_offer
        )

    run_async(scenario())


def test_active_link_cannot_be_rejected() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        await provider.canonical_products.save(_product())
        linked_offer = _offer(canonical_product_id=PRODUCT_A_ID)
        await provider.offers.save(TENANT_A_ID, linked_offer)

        with pytest.raises(CanonicalOfferActiveLinkConflictError):
            await _service(provider).review(
                _command(CanonicalOfferDecisionType.REJECTED),
                _context(),
            )

        assert (
            await provider.canonical_offer_decisions.list_for_offer(
                TENANT_A_ID,
                "ggsel",
                "offer-1",
            )
            == ()
        )

    run_async(scenario())


def test_decision_failure_rolls_back_confirmed_offer_link() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        provider.canonical_offer_decisions = FailingDecisionRepository()
        await provider.canonical_products.save(_product())
        offer = _offer()
        await provider.offers.save(TENANT_A_ID, offer)

        with pytest.raises(RuntimeError, match="controlled decision failure"):
            await _service(provider).review(
                _command(CanonicalOfferDecisionType.CONFIRMED),
                _context(),
            )

        stored_offer = await provider.offers.get_by_identity(
            TENANT_A_ID,
            "ggsel",
            "offer-1",
        )
        assert stored_offer == offer
        assert (
            await provider.canonical_offer_decisions.list_for_offer(
                TENANT_A_ID,
                "ggsel",
                "offer-1",
            )
            == ()
        )

    run_async(scenario())


class FailingDecisionRepository(MemoryCanonicalOfferDecisionRepository):
    """Repository double that fails after the offer link write."""

    async def append(
        self,
        decision: CanonicalOfferDecision,
    ) -> CanonicalOfferDecision:
        del decision
        raise RuntimeError("controlled decision failure")


def _service(provider: RepositoryProvider) -> CanonicalOfferReviewService:
    return CanonicalOfferReviewService(
        create_memory_repository_scope(provider),
        clock=lambda: NOW,
        decision_id_factory=lambda: DECISION_ID,
    )


def _product(
    *,
    tenant_id: UUID = TENANT_A_ID,
    product_id: UUID = PRODUCT_A_ID,
) -> CanonicalProduct:
    return CanonicalProduct(
        id=product_id,
        tenant_id=tenant_id,
        name="Minecraft Java & Bedrock Edition",
        category="Games",
        aliases=("minecraft java bedrock",),
    )


def _offer(
    *,
    tenant_id: UUID = TENANT_A_ID,
    canonical_product_id: UUID | None = None,
) -> ParsedOffer:
    return ParsedOffer(
        tenant_id=tenant_id,
        marketplace="ggsel",
        external_id="offer-1",
        title="Minecraft noisy source title",
        url="https://ggsel.net/en/catalog/product/offer-1",
        price=Decimal("1999.00"),
        currency="RUB",
        canonical_product_id=canonical_product_id,
    )


def _command(
    decision: CanonicalOfferDecisionType,
    *,
    tenant_id: UUID = TENANT_A_ID,
) -> ReviewCanonicalOfferCommand:
    return ReviewCanonicalOfferCommand(
        tenant_id=tenant_id,
        marketplace="ggsel",
        external_id="offer-1",
        canonical_product_id=PRODUCT_A_ID,
        decision=decision,
        reason="not the same edition",
    )


def _context(
    *,
    idempotency_key: str = "review-1",
) -> CanonicalOfferReviewContext:
    return CanonicalOfferReviewContext(
        actor_id="reviewer-1",
        actor_type=AdminActorType.USER,
        request_id="request-1",
        idempotency_key=idempotency_key,
    )
