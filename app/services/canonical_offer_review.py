from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domain.admin_actions import AdminActorType
from app.domain.canonical_offer_decisions import (
    CanonicalOfferDecision,
    CanonicalOfferDecisionType,
    build_canonical_offer_decision_fingerprint,
)
from app.parsers.models import ParsedOffer
from app.repositories.provider import RepositoryProvider
from app.services.canonical_offer_linking import (
    CanonicalProductUnavailableError,
    LinkCanonicalOfferCommand,
    MarketplaceOfferUnavailableError,
    link_canonical_offer,
)
from app.services.repository_scope import RepositoryScopeFactory


@dataclass(slots=True, frozen=True, kw_only=True)
class ReviewCanonicalOfferCommand:
    """One explicit review outcome for an existing offer/product pair."""

    tenant_id: UUID
    marketplace: str
    external_id: str
    canonical_product_id: UUID
    decision: CanonicalOfferDecisionType
    reason: str | None = None


@dataclass(slots=True, frozen=True, kw_only=True)
class CanonicalOfferReviewContext:
    """Authenticated audit and idempotency context for a review command."""

    actor_id: str
    actor_type: AdminActorType
    request_id: str
    idempotency_key: str


@dataclass(slots=True, frozen=True, kw_only=True)
class CanonicalOfferReviewResult:
    """Accepted immutable decision plus replay information."""

    decision: CanonicalOfferDecision
    replayed: bool


class CanonicalOfferReviewError(Exception):
    """Base failure for canonical offer review commands."""


class CanonicalOfferReviewIdempotencyConflictError(CanonicalOfferReviewError):
    """Raised when an idempotency key is reused for different semantics."""


class CanonicalOfferDecisionConflictError(CanonicalOfferReviewError):
    """Raised when a candidate pair already has another terminal decision."""


class CanonicalOfferActiveLinkConflictError(CanonicalOfferReviewError):
    """Raised when rejecting the pair that currently links an offer."""


class CanonicalOfferReviewService:
    """Atomically persist reviewed pair decisions and confirmed offer links."""

    def __init__(
        self,
        repository_scope_factory: RepositoryScopeFactory,
        *,
        clock: Callable[[], datetime] | None = None,
        decision_id_factory: Callable[[], UUID] | None = None,
    ) -> None:
        self._repository_scope_factory = repository_scope_factory
        self._clock = clock or (lambda: datetime.now(UTC))
        self._decision_id_factory = decision_id_factory or uuid4

    async def review(
        self,
        command: ReviewCanonicalOfferCommand,
        context: CanonicalOfferReviewContext,
    ) -> CanonicalOfferReviewResult:
        """Apply one terminal review decision in a single repository scope."""
        fingerprint = build_canonical_offer_decision_fingerprint(
            tenant_id=command.tenant_id,
            marketplace=command.marketplace,
            external_id=command.external_id,
            canonical_product_id=command.canonical_product_id,
            decision=command.decision,
            actor_id=context.actor_id,
            actor_type=context.actor_type,
            reason=command.reason,
        )
        async with self._repository_scope_factory() as repositories:
            decisions = repositories.canonical_offer_decisions
            await decisions.acquire_idempotency_lock(
                command.tenant_id,
                context.idempotency_key,
            )
            existing_replay = await decisions.get_by_idempotency_key(
                command.tenant_id,
                context.idempotency_key,
            )
            if existing_replay is not None:
                _require_same_fingerprint(existing_replay, fingerprint)
                return CanonicalOfferReviewResult(
                    decision=existing_replay,
                    replayed=True,
                )

            await decisions.acquire_pair_lock(
                command.tenant_id,
                command.marketplace,
                command.external_id,
                command.canonical_product_id,
            )
            existing_pair = await decisions.get_for_pair(
                command.tenant_id,
                command.marketplace,
                command.external_id,
                command.canonical_product_id,
            )
            if existing_pair is not None:
                raise CanonicalOfferDecisionConflictError(
                    "Canonical offer pair already has another terminal decision."
                )

            offer = await _require_review_inputs(repositories, command)
            if command.decision is CanonicalOfferDecisionType.CONFIRMED:
                await link_canonical_offer(
                    repositories,
                    LinkCanonicalOfferCommand(
                        tenant_id=command.tenant_id,
                        canonical_product_id=command.canonical_product_id,
                        marketplace=command.marketplace,
                        external_id=command.external_id,
                    ),
                )
            elif offer.canonical_product_id == command.canonical_product_id:
                raise CanonicalOfferActiveLinkConflictError(
                    "An active canonical offer link cannot be rejected."
                )

            decision = CanonicalOfferDecision(
                id=self._decision_id_factory(),
                tenant_id=command.tenant_id,
                marketplace=command.marketplace,
                external_id=command.external_id,
                canonical_product_id=command.canonical_product_id,
                decision=command.decision,
                actor_id=context.actor_id,
                actor_type=context.actor_type,
                request_id=context.request_id,
                idempotency_key=context.idempotency_key,
                request_fingerprint=fingerprint,
                reason=command.reason,
                created_at=self._clock(),
            )
            stored = await decisions.append(decision)
            return CanonicalOfferReviewResult(decision=stored, replayed=False)


async def _require_review_inputs(
    repositories: RepositoryProvider,
    command: ReviewCanonicalOfferCommand,
) -> ParsedOffer:
    product = await repositories.canonical_products.get_by_tenant_and_id(
        command.tenant_id,
        command.canonical_product_id,
    )
    if product is None:
        raise CanonicalProductUnavailableError(
            "Canonical product is unavailable for this tenant."
        )
    offer = await repositories.offers.get_by_identity(
        command.tenant_id,
        command.marketplace,
        command.external_id,
    )
    if offer is None:
        raise MarketplaceOfferUnavailableError(
            "Marketplace offer is unavailable for this tenant."
        )
    return offer


def _require_same_fingerprint(
    existing: CanonicalOfferDecision,
    fingerprint: str,
) -> None:
    if existing.request_fingerprint != fingerprint:
        raise CanonicalOfferReviewIdempotencyConflictError(
            "Idempotency key is bound to another canonical offer decision."
        )
