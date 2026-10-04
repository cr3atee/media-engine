from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from uuid import UUID

from app.domain.canonical_offer_decisions import CanonicalOfferDecision
from app.repositories.base import BaseRepository


class CanonicalOfferDecisionRepository(BaseRepository):
    """Persistence contract for immutable reviewed offer/product decisions."""

    @abstractmethod
    async def acquire_idempotency_lock(
        self,
        tenant_id: UUID,
        idempotency_key: str,
    ) -> None:
        """Serialize commands sharing one tenant-scoped idempotency key."""

    @abstractmethod
    async def acquire_pair_lock(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
        canonical_product_id: UUID,
    ) -> None:
        """Serialize decisions for one tenant-owned candidate pair."""

    @abstractmethod
    async def append(
        self,
        decision: CanonicalOfferDecision,
    ) -> CanonicalOfferDecision:
        """Append one immutable decision without replacing prior evidence."""

    @abstractmethod
    async def get_by_id(self, decision_id: UUID) -> CanonicalOfferDecision | None:
        """Return one decision by identifier."""

    @abstractmethod
    async def get_by_idempotency_key(
        self,
        tenant_id: UUID,
        idempotency_key: str,
    ) -> CanonicalOfferDecision | None:
        """Return a decision by tenant-scoped idempotency key."""

    @abstractmethod
    async def get_for_pair(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
        canonical_product_id: UUID,
    ) -> CanonicalOfferDecision | None:
        """Return the terminal decision for one offer/product pair."""

    @abstractmethod
    async def list_by_tenant(
        self,
        tenant_id: UUID,
    ) -> Sequence[CanonicalOfferDecision]:
        """Return all terminal decisions for one tenant in stable order."""

    @abstractmethod
    async def list_for_offer(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
    ) -> Sequence[CanonicalOfferDecision]:
        """Return reviewed candidate decisions for one marketplace offer."""
