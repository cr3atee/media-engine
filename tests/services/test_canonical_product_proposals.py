from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from app.domain.admin_actions import AdminActorType
from app.domain.canonical_offer_decisions import CanonicalOfferDecision
from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer
from app.repositories.memory import MemoryCanonicalOfferDecisionRepository
from app.repositories.provider import create_memory_provider
from app.services.canonical_offer_linking import MarketplaceOfferUnavailableError
from app.services.canonical_offer_review import (
    CanonicalOfferDecisionConflictError,
    CanonicalOfferReviewContext,
    CanonicalOfferReviewIdempotencyConflictError,
)
from app.services.canonical_offer_review_queue import (
    CanonicalOfferReviewQueueService,
    canonical_product_proposal_id,
)
from app.services.canonical_product_proposals import (
    CanonicalProductProposalConfirmationResult,
    CanonicalProductProposalService,
    CanonicalProductProposalUnavailableError,
    ConfirmCanonicalProductProposalCommand,
)
from app.services.repository_scope import create_memory_repository_scope

TENANT_A_ID = UUID("3c000000-0000-4000-8000-000000001001")
TENANT_B_ID = UUID("3c000000-0000-4000-8000-000000001002")
EXISTING_PRODUCT_ID = UUID("3c000000-0000-4000-8000-000000002001")
DECISION_ID = UUID("3c000000-0000-4000-8000-000000003001")
NOW = datetime(2026, 10, 4, 16, 0, tzinfo=UTC)


class FailingDecisionRepository(MemoryCanonicalOfferDecisionRepository):
    """Fail after product and link writes to exercise scope rollback."""

    async def append(
        self,
        decision: CanonicalOfferDecision,
    ) -> CanonicalOfferDecision:
        del decision
        raise RuntimeError("controlled proposal decision failure")


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run one proposal scenario without an async pytest plugin."""
    return asyncio.run(awaitable)


def test_confirmation_creates_links_audits_and_replays_atomically() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        offer = _offer(title="  Stardew   Valley Complete  ")
        await provider.offers.save(TENANT_A_ID, offer)
        scope = create_memory_repository_scope(provider)
        service = _service(scope)
        command = _command(offer)
        context = _context("proposal-confirm")

        confirmed = await service.confirm(command, context)
        replayed = await service.confirm(command, context)

        stored_product = await provider.canonical_products.get_by_tenant_and_id(
            TENANT_A_ID,
            command.proposal_id,
        )
        stored_offer = await provider.offers.get_by_identity(
            TENANT_A_ID,
            "ggsel",
            "proposal-offer",
        )
        decisions = await provider.canonical_offer_decisions.list_for_offer(
            TENANT_A_ID,
            "ggsel",
            "proposal-offer",
        )
        proposals = await CanonicalOfferReviewQueueService(
            scope
        ).list_product_proposals(TENANT_A_ID)

        assert confirmed.product.id == command.proposal_id
        assert confirmed.product.name == "Stardew Valley Complete"
        assert confirmed.product.category is None
        assert confirmed.product.aliases == ()
        assert confirmed.offer.canonical_product_id == command.proposal_id
        assert confirmed.decision.id == DECISION_ID
        assert confirmed.replayed is False
        assert replayed.replayed is True
        assert replayed.decision == confirmed.decision
        assert stored_product == confirmed.product
        assert stored_offer is not None
        assert stored_offer.canonical_product_id == command.proposal_id
        assert decisions == (confirmed.decision,)
        assert proposals == ()

    run_async(scenario())


def test_confirmation_rejects_idempotency_fingerprint_reuse() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        offer = _offer()
        await provider.offers.save(TENANT_A_ID, offer)
        service = _service(create_memory_repository_scope(provider))
        context = _context("shared-key")
        await service.confirm(_command(offer), context)

        with pytest.raises(CanonicalOfferReviewIdempotencyConflictError):
            await service.confirm(
                _command(offer, reason="Different semantics"),
                context,
            )

    run_async(scenario())


def test_confirmation_requires_current_no_match_proposal() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        offer = _offer(title="Minecraft Java Bedrock Windows")
        await provider.offers.save(TENANT_A_ID, offer)
        await provider.canonical_products.save(
            CanonicalProduct(
                id=EXISTING_PRODUCT_ID,
                tenant_id=TENANT_A_ID,
                name="Minecraft Java Bedrock Windows",
                category="Games",
                aliases=(),
            )
        )
        service = _service(create_memory_repository_scope(provider))

        with pytest.raises(CanonicalProductProposalUnavailableError):
            await service.confirm(_command(offer), _context("auto-match"))
        with pytest.raises(CanonicalProductProposalUnavailableError):
            await service.confirm(
                ConfirmCanonicalProductProposalCommand(
                    tenant_id=TENANT_A_ID,
                    proposal_id=UUID("3c000000-0000-4000-8000-000000009999"),
                    marketplace="ggsel",
                    external_id="proposal-offer",
                ),
                _context("wrong-proposal"),
            )

        products = await provider.canonical_products.list_by_tenant(TENANT_A_ID)
        stored_offer = await provider.offers.get_by_identity(
            TENANT_A_ID,
            "ggsel",
            "proposal-offer",
        )
        assert products == (
            CanonicalProduct(
                id=EXISTING_PRODUCT_ID,
                tenant_id=TENANT_A_ID,
                name="Minecraft Java Bedrock Windows",
                category="Games",
                aliases=(),
            ),
        )
        assert stored_offer is not None
        assert stored_offer.canonical_product_id is None

    run_async(scenario())


def test_confirmation_is_tenant_isolated() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        offer = _offer()
        await provider.offers.save(TENANT_A_ID, offer)
        service = _service(create_memory_repository_scope(provider))
        command = ConfirmCanonicalProductProposalCommand(
            tenant_id=TENANT_B_ID,
            proposal_id=canonical_product_proposal_id(TENANT_B_ID, offer),
            marketplace="ggsel",
            external_id="proposal-offer",
        )

        with pytest.raises(MarketplaceOfferUnavailableError):
            await service.confirm(command, _context("foreign-tenant"))

        assert await provider.canonical_products.list_by_tenant(TENANT_B_ID) == ()

    run_async(scenario())


def test_confirmation_rolls_back_product_and_link_when_audit_fails() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        provider.canonical_offer_decisions = FailingDecisionRepository()
        offer = _offer()
        await provider.offers.save(TENANT_A_ID, offer)
        command = _command(offer)

        with pytest.raises(RuntimeError, match="controlled proposal decision"):
            await _service(create_memory_repository_scope(provider)).confirm(
                command,
                _context("rollback"),
            )

        assert await provider.canonical_products.get_by_id(command.proposal_id) is None
        stored_offer = await provider.offers.get_by_identity(
            TENANT_A_ID,
            "ggsel",
            "proposal-offer",
        )
        assert stored_offer is not None
        assert stored_offer.canonical_product_id is None

    run_async(scenario())


def test_concurrent_keys_create_only_one_product() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        offer = _offer()
        await provider.offers.save(TENANT_A_ID, offer)
        service = _service(create_memory_repository_scope(provider))
        command = _command(offer)

        results = await asyncio.gather(
            service.confirm(command, _context("concurrent-a")),
            service.confirm(command, _context("concurrent-b")),
            return_exceptions=True,
        )

        accepted = [
            result
            for result in results
            if isinstance(result, CanonicalProductProposalConfirmationResult)
        ]
        conflicts = [
            result
            for result in results
            if isinstance(result, CanonicalOfferDecisionConflictError)
        ]
        products = await provider.canonical_products.list_by_tenant(TENANT_A_ID)
        assert len(accepted) == 1
        assert len(conflicts) == 1
        assert len(products) == 1
        assert products[0].id == command.proposal_id

    run_async(scenario())


def _service(scope: Any) -> CanonicalProductProposalService:
    return CanonicalProductProposalService(
        scope,
        clock=lambda: NOW,
        decision_id_factory=lambda: DECISION_ID,
    )


def _offer(*, title: str = "Stardew Valley Complete") -> ParsedOffer:
    return ParsedOffer(
        tenant_id=TENANT_A_ID,
        marketplace="ggsel",
        external_id="proposal-offer",
        title=title,
        url="https://ggsel.net/catalog/product/proposal-offer",
        price=Decimal("499.00"),
        currency="RUB",
    )


def _command(
    offer: ParsedOffer,
    *,
    reason: str | None = "Verified source product",
) -> ConfirmCanonicalProductProposalCommand:
    return ConfirmCanonicalProductProposalCommand(
        tenant_id=TENANT_A_ID,
        proposal_id=canonical_product_proposal_id(TENANT_A_ID, offer),
        marketplace="ggsel",
        external_id="proposal-offer",
        reason=reason,
    )


def _context(idempotency_key: str) -> CanonicalOfferReviewContext:
    return CanonicalOfferReviewContext(
        actor_id="reviewer-1",
        actor_type=AdminActorType.USER,
        request_id=f"request-{idempotency_key}",
        idempotency_key=idempotency_key,
    )
