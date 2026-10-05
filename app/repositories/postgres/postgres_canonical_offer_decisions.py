from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.admin_actions import AdminActorType
from app.domain.canonical_offer_decisions import (
    CanonicalOfferDecision,
    CanonicalOfferDecisionType,
)
from app.models.canonical_offer_decision_record import CanonicalOfferDecisionRecord
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.canonical_offer_decisions import (
    CanonicalOfferDecisionRepository,
)


class PostgresCanonicalOfferDecisionRepository(CanonicalOfferDecisionRepository):
    """PostgreSQL append-only storage for canonical offer decisions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def acquire_idempotency_lock(
        self,
        tenant_id: UUID,
        idempotency_key: str,
    ) -> None:
        """Acquire a transaction-scoped advisory lock for one command key."""
        if not idempotency_key.strip():
            msg = "Idempotency key must not be empty."
            raise ValueError(msg)
        await self._acquire_lock(
            f"canonical-decision:key:{tenant_id}:{idempotency_key}"
        )

    async def acquire_pair_lock(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
        canonical_product_id: UUID,
    ) -> None:
        """Acquire a transaction-scoped advisory lock for one candidate pair."""
        await self._acquire_lock(
            "canonical-decision:pair:"
            f"{tenant_id}:{marketplace.strip().lower()}:"
            f"{external_id.strip()}:{canonical_product_id}"
        )

    async def acquire_offer_lock(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
    ) -> None:
        """Acquire a transaction-scoped lock for all decisions on one offer."""
        await self._acquire_lock(
            "canonical-decision:offer:"
            f"{tenant_id}:{marketplace.strip().lower()}:{external_id.strip()}"
        )

    async def append(
        self,
        decision: CanonicalOfferDecision,
    ) -> CanonicalOfferDecision:
        """Append one immutable decision inside the caller-owned transaction."""
        existing = await self.get_by_idempotency_key(
            decision.tenant_id,
            decision.idempotency_key,
        )
        if existing is not None:
            if existing.request_fingerprint != decision.request_fingerprint:
                msg = "Idempotency key is bound to another canonical offer decision."
                raise RepositoryIdentityConflictError(msg)
            return existing
        if (
            await self.get_for_pair(
                decision.tenant_id,
                decision.marketplace,
                decision.external_id,
                decision.canonical_product_id,
            )
            is not None
        ):
            msg = "Canonical offer pair already has a terminal decision."
            raise RepositoryIdentityConflictError(msg)
        if await self.get_by_id(decision.id) is not None:
            msg = "Canonical offer decision ID is already in use."
            raise RepositoryIdentityConflictError(msg)
        self._session.add(_to_record(decision))
        await self._session.flush()
        return decision

    async def get_by_id(self, decision_id: UUID) -> CanonicalOfferDecision | None:
        """Return one decision by identifier."""
        record = await self._session.get(CanonicalOfferDecisionRecord, decision_id)
        return _to_domain(record) if record is not None else None

    async def get_by_idempotency_key(
        self,
        tenant_id: UUID,
        idempotency_key: str,
    ) -> CanonicalOfferDecision | None:
        """Return one decision by tenant-scoped idempotency key."""
        result = await self._session.execute(
            select(CanonicalOfferDecisionRecord).where(
                CanonicalOfferDecisionRecord.tenant_id == tenant_id,
                CanonicalOfferDecisionRecord.idempotency_key == idempotency_key,
            )
        )
        record = result.scalar_one_or_none()
        return _to_domain(record) if record is not None else None

    async def get_for_pair(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
        canonical_product_id: UUID,
    ) -> CanonicalOfferDecision | None:
        """Return one terminal pair decision."""
        result = await self._session.execute(
            select(CanonicalOfferDecisionRecord).where(
                CanonicalOfferDecisionRecord.tenant_id == tenant_id,
                CanonicalOfferDecisionRecord.marketplace == marketplace.strip().lower(),
                CanonicalOfferDecisionRecord.external_id == external_id.strip(),
                CanonicalOfferDecisionRecord.canonical_product_id
                == canonical_product_id,
            )
        )
        record = result.scalar_one_or_none()
        return _to_domain(record) if record is not None else None

    async def list_for_offer(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
    ) -> Sequence[CanonicalOfferDecision]:
        """Return decisions for one offer in deterministic chronological order."""
        result = await self._session.execute(
            select(CanonicalOfferDecisionRecord)
            .where(
                CanonicalOfferDecisionRecord.tenant_id == tenant_id,
                CanonicalOfferDecisionRecord.marketplace == marketplace.strip().lower(),
                CanonicalOfferDecisionRecord.external_id == external_id.strip(),
            )
            .order_by(
                CanonicalOfferDecisionRecord.created_at,
                CanonicalOfferDecisionRecord.id,
            )
        )
        return tuple(_to_domain(record) for record in result.scalars())

    async def list_by_tenant(
        self,
        tenant_id: UUID,
    ) -> Sequence[CanonicalOfferDecision]:
        """Return tenant-owned decisions in deterministic chronological order."""
        result = await self._session.execute(
            select(CanonicalOfferDecisionRecord)
            .where(CanonicalOfferDecisionRecord.tenant_id == tenant_id)
            .order_by(
                CanonicalOfferDecisionRecord.created_at,
                CanonicalOfferDecisionRecord.id,
            )
        )
        return tuple(_to_domain(record) for record in result.scalars())

    async def _acquire_lock(self, key: str) -> None:
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": key},
        )


def _to_record(decision: CanonicalOfferDecision) -> CanonicalOfferDecisionRecord:
    return CanonicalOfferDecisionRecord(
        id=decision.id,
        tenant_id=decision.tenant_id,
        marketplace=decision.marketplace,
        external_id=decision.external_id,
        canonical_product_id=decision.canonical_product_id,
        decision=decision.decision.value,
        actor_id=decision.actor_id,
        actor_type=decision.actor_type.value,
        request_id=decision.request_id,
        idempotency_key=decision.idempotency_key,
        request_fingerprint=decision.request_fingerprint,
        reason=decision.reason,
        created_at=decision.created_at,
    )


def _to_domain(record: CanonicalOfferDecisionRecord) -> CanonicalOfferDecision:
    return CanonicalOfferDecision(
        id=record.id,
        tenant_id=record.tenant_id,
        marketplace=record.marketplace,
        external_id=record.external_id,
        canonical_product_id=record.canonical_product_id,
        decision=CanonicalOfferDecisionType(record.decision),
        actor_id=record.actor_id,
        actor_type=AdminActorType(record.actor_type),
        request_id=record.request_id,
        idempotency_key=record.idempotency_key,
        request_fingerprint=record.request_fingerprint,
        reason=record.reason,
        created_at=record.created_at,
    )
