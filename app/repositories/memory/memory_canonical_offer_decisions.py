from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from app.domain.canonical_offer_decisions import CanonicalOfferDecision
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.canonical_offer_decisions import (
    CanonicalOfferDecisionRepository,
)

type DecisionPairKey = tuple[UUID, str, str, UUID]


class MemoryCanonicalOfferDecisionRepository(CanonicalOfferDecisionRepository):
    """In-memory append-only storage for canonical offer review decisions."""

    def __init__(self) -> None:
        self._decisions_by_id: dict[UUID, CanonicalOfferDecision] = {}
        self._decision_ids_by_idempotency: dict[tuple[UUID, str], UUID] = {}
        self._decision_ids_by_pair: dict[DecisionPairKey, UUID] = {}

    async def acquire_idempotency_lock(
        self,
        tenant_id: UUID,
        idempotency_key: str,
    ) -> None:
        """Rely on the enclosing serialized memory repository scope."""
        del tenant_id
        if not idempotency_key.strip():
            msg = "Idempotency key must not be empty."
            raise ValueError(msg)

    async def acquire_pair_lock(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
        canonical_product_id: UUID,
    ) -> None:
        """Rely on the enclosing serialized memory repository scope."""
        del tenant_id, marketplace, external_id, canonical_product_id

    async def acquire_offer_lock(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
    ) -> None:
        """Rely on the enclosing serialized memory repository scope."""
        del tenant_id, marketplace, external_id

    async def append(
        self,
        decision: CanonicalOfferDecision,
    ) -> CanonicalOfferDecision:
        """Append one decision while enforcing idempotency and pair identity."""
        idempotency_key = (decision.tenant_id, decision.idempotency_key)
        existing_id = self._decision_ids_by_idempotency.get(idempotency_key)
        if existing_id is not None:
            existing = self._decisions_by_id[existing_id]
            if existing.request_fingerprint != decision.request_fingerprint:
                msg = "Idempotency key is bound to another canonical offer decision."
                raise RepositoryIdentityConflictError(msg)
            return existing

        pair_key = _pair_key(decision)
        if pair_key in self._decision_ids_by_pair:
            msg = "Canonical offer pair already has a terminal decision."
            raise RepositoryIdentityConflictError(msg)
        if decision.id in self._decisions_by_id:
            msg = "Canonical offer decision ID is already in use."
            raise RepositoryIdentityConflictError(msg)

        self._decisions_by_id[decision.id] = decision
        self._decision_ids_by_idempotency[idempotency_key] = decision.id
        self._decision_ids_by_pair[pair_key] = decision.id
        return decision

    async def get_by_id(self, decision_id: UUID) -> CanonicalOfferDecision | None:
        """Return one decision by identifier."""
        return self._decisions_by_id.get(decision_id)

    async def get_by_idempotency_key(
        self,
        tenant_id: UUID,
        idempotency_key: str,
    ) -> CanonicalOfferDecision | None:
        """Return one decision by tenant-scoped idempotency key."""
        decision_id = self._decision_ids_by_idempotency.get(
            (tenant_id, idempotency_key)
        )
        return (
            self._decisions_by_id.get(decision_id) if decision_id is not None else None
        )

    async def get_for_pair(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
        canonical_product_id: UUID,
    ) -> CanonicalOfferDecision | None:
        """Return one terminal pair decision."""
        decision_id = self._decision_ids_by_pair.get(
            (
                tenant_id,
                marketplace.strip().lower(),
                external_id.strip(),
                canonical_product_id,
            )
        )
        return (
            self._decisions_by_id.get(decision_id) if decision_id is not None else None
        )

    async def list_for_offer(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
    ) -> Sequence[CanonicalOfferDecision]:
        """Return decisions for one offer in deterministic chronological order."""
        normalized_marketplace = marketplace.strip().lower()
        normalized_external_id = external_id.strip()
        return tuple(
            sorted(
                (
                    decision
                    for decision in self._decisions_by_id.values()
                    if decision.tenant_id == tenant_id
                    and decision.marketplace == normalized_marketplace
                    and decision.external_id == normalized_external_id
                ),
                key=lambda decision: (decision.created_at, decision.id.hex),
            )
        )

    async def list_by_tenant(
        self,
        tenant_id: UUID,
    ) -> Sequence[CanonicalOfferDecision]:
        """Return tenant-owned decisions in deterministic chronological order."""
        return tuple(
            sorted(
                (
                    decision
                    for decision in self._decisions_by_id.values()
                    if decision.tenant_id == tenant_id
                ),
                key=lambda decision: (decision.created_at, decision.id.hex),
            )
        )


def _pair_key(decision: CanonicalOfferDecision) -> DecisionPairKey:
    return (
        decision.tenant_id,
        decision.marketplace,
        decision.external_id,
        decision.canonical_product_id,
    )
