from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from app.domain.admin_actions import (
    AdminAction,
    AdminActionType,
    AdminActorType,
    AdminResourceType,
)
from app.domain.offer_availability import OfferAvailabilityStatus
from app.parsers.models import ParsedOffer
from app.repositories.memory.memory_admin_actions import MemoryAdminActionRepository
from app.repositories.provider import RepositoryProvider, create_memory_provider
from app.services.admin_mutations import (
    AdminCommandContext,
    AdminCommandError,
    AdminMutationService,
    OfferAvailabilityCommand,
)
from app.services.repository_scope import create_memory_repository_scope
from tests.repositories.contracts.factories import run_async

TENANT_ID = UUID("5b000000-0000-4000-8000-000000000001")
FOREIGN_TENANT_ID = UUID("5b000000-0000-4000-8000-000000000002")
PRODUCT_ID = UUID("5b000000-0000-4000-8000-000000000003")
NOW = datetime(2026, 10, 28, 8, 0, tzinfo=UTC)


def test_offer_retire_restore_is_audited_idempotent_and_non_destructive() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        offer = _offer()
        await provider.offers.save(TENANT_ID, offer)
        service = _service(provider)

        initial = await service.get_offer_availability(
            TENANT_ID,
            offer.marketplace,
            offer.external_id or "",
        )
        assert initial is not None
        assert initial.status is OfferAvailabilityStatus.ACTIVE
        assert initial.version == 1

        command = _command(expected_version=1, reason="Marketplace link returns 404")
        first = await service.retire_offer(command, _context("retire-funpay"))
        replay = await service.retire_offer(command, _context("retire-funpay"))

        assert first.action is AdminActionType.RETIRE_OFFER
        assert first.resource_type is AdminResourceType.OFFER
        assert first.previous_state == OfferAvailabilityStatus.ACTIVE.value
        assert first.resulting_state == OfferAvailabilityStatus.RETIRED.value
        assert first.resulting_version == 2
        assert first.replayed is False
        assert replay.action_id == first.action_id
        assert replay.replayed is True
        await provider.offers.save(TENANT_ID, offer)
        assert (
            await provider.offers.get_by_identity(
                TENANT_ID,
                offer.marketplace,
                offer.external_id,
            )
            is None
        )
        assert await provider.offers.list_by_tenant(TENANT_ID) == ()

        retired = await service.get_offer_availability(
            TENANT_ID,
            offer.marketplace,
            offer.external_id or "",
        )
        assert retired is not None
        assert retired.status is OfferAvailabilityStatus.RETIRED
        assert retired.version == 2
        assert retired.retired_at == NOW

        with pytest.raises(AdminCommandError) as reused:
            await service.restore_offer(
                _command(expected_version=2, reason="Link is reachable again"),
                _context("retire-funpay"),
            )
        assert reused.value.code == "idempotency_conflict"

        with pytest.raises(AdminCommandError) as stale:
            await service.restore_offer(
                _command(expected_version=1, reason="Link is reachable again"),
                _context("restore-stale"),
            )
        assert stale.value.code == "optimistic_concurrency_conflict"

        restored = await service.restore_offer(
            _command(expected_version=2, reason="Link is reachable again"),
            _context("restore-funpay"),
        )
        assert restored.action is AdminActionType.RESTORE_OFFER
        assert restored.previous_state == OfferAvailabilityStatus.RETIRED.value
        assert restored.resulting_state == OfferAvailabilityStatus.ACTIVE.value
        assert restored.resulting_version == 3

        visible = await provider.offers.get_by_identity(
            TENANT_ID,
            offer.marketplace,
            offer.external_id,
        )
        assert visible == offer
        assert visible.canonical_product_id == PRODUCT_ID
        active = await service.get_offer_availability(
            TENANT_ID,
            offer.marketplace,
            offer.external_id or "",
        )
        assert active is not None
        assert active.status is OfferAvailabilityStatus.ACTIVE
        assert active.version == 3
        assert active.retired_at is None

        actions = await provider.admin_actions.list_for_resource(
            AdminResourceType.OFFER,
            initial.offer_id,
        )
        assert {action.action for action in actions} == {
            AdminActionType.RETIRE_OFFER,
            AdminActionType.RESTORE_OFFER,
        }
        retire_action = next(
            action
            for action in actions
            if action.action is AdminActionType.RETIRE_OFFER
        )
        assert retire_action.reason == "Marketplace link returns 404"
        assert retire_action.metadata == (
            ("external_id", "80145738"),
            ("marketplace", "funpay"),
        )

    run_async(scenario())


def test_offer_availability_is_tenant_isolated() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        await provider.offers.save(TENANT_ID, _offer())
        service = _service(provider)

        with pytest.raises(AdminCommandError) as error:
            await service.retire_offer(
                _command(expected_version=1, reason="Foreign tenant request"),
                _context("foreign-retire", tenant_id=FOREIGN_TENANT_ID),
            )

        assert error.value.code == "resource_not_found"
        state = await service.get_offer_availability(TENANT_ID, "funpay", "80145738")
        assert state is not None
        assert state.status is OfferAvailabilityStatus.ACTIVE
        assert not await provider.admin_actions.list_for_resource(
            AdminResourceType.OFFER,
            state.offer_id,
        )

    run_async(scenario())


def test_offer_retirement_rolls_back_when_audit_append_fails() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        await provider.offers.save(TENANT_ID, _offer())
        provider.admin_actions = _FailingAdminActionRepository()
        service = _service(provider)

        with pytest.raises(RuntimeError, match="audit storage unavailable"):
            await service.retire_offer(
                _command(expected_version=1, reason="Marketplace link returns 404"),
                _context("rollback-retire"),
            )

        state = await service.get_offer_availability(TENANT_ID, "funpay", "80145738")
        assert state is not None
        assert state.status is OfferAvailabilityStatus.ACTIVE
        assert state.version == 1
        assert (
            await provider.offers.get_by_identity(
                TENANT_ID,
                "funpay",
                "80145738",
            )
            == _offer()
        )

    run_async(scenario())


class _FailingAdminActionRepository(MemoryAdminActionRepository):
    async def append(self, action: AdminAction) -> AdminAction:
        del action
        raise RuntimeError("audit storage unavailable")


def _service(provider: RepositoryProvider) -> AdminMutationService:
    return AdminMutationService(
        create_memory_repository_scope(provider),
        maximum_publication_attempts=5,
        clock=lambda: NOW,
    )


def _context(
    idempotency_key: str,
    *,
    tenant_id: UUID = TENANT_ID,
) -> AdminCommandContext:
    return AdminCommandContext(
        actor_id="catalog-reviewer",
        actor_type=AdminActorType.USER,
        tenant_id=tenant_id,
        request_id=f"request-{idempotency_key}",
        idempotency_key=idempotency_key,
    )


def _command(*, expected_version: int, reason: str) -> OfferAvailabilityCommand:
    return OfferAvailabilityCommand(
        tenant_id=TENANT_ID,
        marketplace="funpay",
        external_id="80145738",
        expected_version=expected_version,
        reason=reason,
    )


def _offer() -> ParsedOffer:
    return ParsedOffer(
        tenant_id=TENANT_ID,
        marketplace="funpay",
        external_id="80145738",
        title="Minecraft Java and Bedrock Edition",
        url="https://funpay.com/lots/offer?id=80145738",
        price=Decimal("799.00"),
        currency="RUB",
        canonical_product_id=PRODUCT_ID,
    )
