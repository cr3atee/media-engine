from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
from uuid import UUID, uuid4

import pytest

from app.domain.activation_conditions import (
    AccountRequirement,
    ActivationConditions,
    DeliveryMethod,
)
from app.domain.admin_actions import AdminAction, AdminActorType, AdminResourceType
from app.parsers.models import ParsedOffer
from app.repositories.memory.memory_admin_actions import MemoryAdminActionRepository
from app.repositories.provider import RepositoryProvider, create_memory_provider
from app.services.admin_mutations import AdminCommandContext
from app.services.offer_activation_review import (
    ActivationReviewError,
    OfferActivationReviewService,
    ReviewActivationConditionsCommand,
)
from app.services.repository_scope import create_memory_repository_scope

TENANT = UUID(int=26001)
TERMS = ActivationConditions(
    regions=("RU", "KZ"),
    excluded_regions=(),
    device="pc",
    plan="solo",
    period="P1M",
    delivery_method=DeliveryMethod.KEY,
    account_requirement=AccountRequirement.ANY,
    vpn_required=False,
    activation_window_seconds=None,
)


def _offer() -> ParsedOffer:
    return ParsedOffer(
        tenant_id=TENANT,
        marketplace="ggsel",
        external_id="synthetic-1",
        title="Offline fixture subscription " + "x " * 300,
        url="https://example.com/test-only",
        price=Decimal("500"),
        currency="RUB",
        canonical_product_id=UUID(int=26002),
    )


def _context(key: str = "activation-review") -> AdminCommandContext:
    return AdminCommandContext(
        tenant_id=TENANT,
        actor_id="synthetic-reviewer",
        actor_type=AdminActorType.USER,
        request_id=key,
        idempotency_key=key,
    )


async def _setup(
    provider: RepositoryProvider | None = None,
) -> tuple[
    RepositoryProvider, OfferActivationReviewService, ReviewActivationConditionsCommand
]:
    provider = provider or create_memory_provider()
    await provider.offers.save(_offer())
    service = OfferActivationReviewService(create_memory_repository_scope(provider))
    state = await service.get(TENANT, "ggsel", "synthetic-1")
    return (
        provider,
        service,
        ReviewActivationConditionsCommand(
            tenant_id=TENANT,
            marketplace="ggsel",
            external_id="synthetic-1",
            offer_id=state.offer_id,
            expected_version=state.version,
            expected_source_fingerprint=state.source_fingerprint,
            conditions=TERMS,
            reason="Synthetic fixture facts, not real marketplace verification.",
        ),
    )


def test_review_is_atomic_audited_replayable_and_condition_only() -> None:
    async def scenario() -> None:
        provider, service, command = await _setup()
        result = await service.review(command, _context())
        replay = await service.review(
            command, replace(_context(), request_id="another-request")
        )
        assert result.replayed is False and replay.replayed is True
        assert replay.action_id == result.action_id
        assert result.resulting_version == 2
        stored = await provider.offers.get_by_identity(TENANT, "ggsel", "synthetic-1")
        assert stored == replace(_offer(), activation_conditions=TERMS)
        availability = await provider.offers.get_availability_state(
            TENANT, "ggsel", "synthetic-1"
        )
        assert availability is not None and availability.version == 1
        actions = await provider.admin_actions.list_for_resource(
            AdminResourceType.OFFER, result.resource_id
        )
        assert len(actions) == 1
        action = actions[0]
        assert (
            action.actor_id == "synthetic-reviewer" and action.reason == command.reason
        )
        metadata = dict(action.metadata)
        raw = base64.b64decode(
            "".join(
                metadata[key]
                for key in sorted(metadata)
                if key.startswith("source_b64_")
            )
        )
        assert sha256(raw).hexdigest() == command.expected_source_fingerprint
        assert json.loads(raw)["title"] == _offer().title
        profile = base64.b64decode(
            "".join(
                metadata[key]
                for key in sorted(metadata)
                if key.startswith("conditions_b64_")
            )
        )
        assert ActivationConditions.from_record(json.loads(profile)) == TERMS
        state = await service.get(TENANT, "ggsel", "synthetic-1")
        cleared = await service.review(
            replace(
                command,
                expected_version=state.version,
                expected_source_fingerprint=state.source_fingerprint,
                conditions=None,
            ),
            _context("explicit-clear"),
        )
        assert cleared.resulting_state == "unknown" and cleared.resulting_version == 3
        assert (
            await service.get(TENANT, "ggsel", "synthetic-1")
        ).offer.activation_conditions is None

    asyncio.run(scenario())


@pytest.mark.parametrize("case", ["tenant", "offer_id", "version", "source", "reason"])
def test_stale_or_unauthorized_commands_do_not_write(case: str) -> None:
    async def scenario() -> None:
        provider, service, command = await _setup()
        if case == "tenant":
            command = replace(command, tenant_id=uuid4())
        elif case == "offer_id":
            command = replace(command, offer_id=uuid4())
        elif case == "version":
            command = replace(command, expected_version=2)
        elif case == "source":
            command = replace(command, expected_source_fingerprint="0" * 64)
        else:
            command = replace(command, reason="  ")
        with pytest.raises(ActivationReviewError):
            await service.review(command, _context())
        assert (
            await provider.offers.get_by_identity(TENANT, "ggsel", "synthetic-1")
            == _offer()
        )
        assert not await provider.admin_actions.list_for_resource(
            AdminResourceType.OFFER, command.offer_id
        )

    asyncio.run(scenario())


def test_changed_price_and_conflicting_idempotency_are_rejected() -> None:
    async def scenario() -> None:
        provider, service, command = await _setup()
        await provider.offers.save(replace(_offer(), price=Decimal("450")))
        with pytest.raises(ActivationReviewError, match="activation_source_conflict"):
            await service.review(command, _context())
        fresh = await service.get(TENANT, "ggsel", "synthetic-1")
        command = replace(command, expected_source_fingerprint=fresh.source_fingerprint)
        await service.review(command, _context())
        with pytest.raises(ActivationReviewError, match="idempotency_conflict"):
            await service.review(replace(command, conditions=None), _context())
        assert (
            await service.get(TENANT, "ggsel", "synthetic-1")
        ).offer.price == Decimal("450")

    asyncio.run(scenario())


class FailingAudit(MemoryAdminActionRepository):
    """Fail after the profile CAS to exercise transaction rollback."""

    async def append(self, action: AdminAction) -> AdminAction:
        raise RuntimeError("controlled audit failure")


def test_audit_failure_rolls_back_condition_update() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        provider.admin_actions = FailingAudit()
        provider, service, command = await _setup(provider)
        with pytest.raises(RuntimeError, match="controlled audit failure"):
            await service.review(command, _context())
        assert (
            await provider.offers.get_by_identity(TENANT, "ggsel", "synthetic-1")
            == _offer()
        )

    asyncio.run(scenario())


def test_conflicting_reviews_have_one_winner() -> None:
    async def scenario() -> None:
        provider, service, command = await _setup()
        results = await asyncio.gather(
            service.review(command, _context("one")),
            service.review(
                replace(command, conditions=replace(TERMS, regions=("BR",))),
                _context("two"),
            ),
            return_exceptions=True,
        )
        assert sum(isinstance(item, ActivationReviewError) for item in results) == 1
        assert (
            len(
                await provider.admin_actions.list_for_resource(
                    AdminResourceType.OFFER, command.offer_id
                )
            )
            == 1
        )

    asyncio.run(scenario())


def test_repository_cas_does_not_replace_a_new_source_price() -> None:
    async def scenario() -> None:
        provider, _, _ = await _setup()
        expected = replace(_offer())
        await provider.offers.save(replace(expected, price=Decimal("450")))
        assert not await provider.offers.compare_and_set_activation_conditions(
            TENANT, expected, TERMS
        )
        stored = await provider.offers.get_by_identity(TENANT, "ggsel", "synthetic-1")
        assert (
            stored is not None
            and stored.price == Decimal("450")
            and stored.activation_conditions is None
        )

    asyncio.run(scenario())
