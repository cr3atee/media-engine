from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from app.domain.lifecycle import EventDisposition
from app.domain.market_events import (
    ClaimedMarketEvent,
    EventAddResult,
    MarketEventCandidate,
    PriceDropMarketEvent,
)
from app.domain.processing import ProcessingError, StateTransitionResult
from app.repositories.base import BaseRepository


class MarketEventRepository(BaseRepository):
    """Async persistence contract for persistent market-event lifecycles."""

    @abstractmethod
    async def add_idempotently(
        self,
        candidate: MarketEventCandidate,
    ) -> EventAddResult:
        """Persist an event once by its deterministic identity."""

    @abstractmethod
    async def get_by_id(self, event_id: UUID) -> PriceDropMarketEvent | None:
        """Return a market event by technical identifier."""

    @abstractmethod
    async def get_by_identity(
        self,
        identity_key: str,
    ) -> PriceDropMarketEvent | None:
        """Return a market event by deterministic identity."""

    @abstractmethod
    async def list_pending(
        self,
        now: datetime,
        limit: int,
    ) -> Sequence[PriceDropMarketEvent]:
        """Return scoring work eligible at the supplied UTC time."""

    @abstractmethod
    async def claim_pending(
        self,
        now: datetime,
        worker_id: str,
        lease_until: datetime,
        limit: int,
    ) -> Sequence[ClaimedMarketEvent]:
        """Claim eligible scoring work without owning transaction commit."""

    @abstractmethod
    async def list_expired_scoring_claims(
        self,
        now: datetime,
        limit: int,
    ) -> Sequence[ClaimedMarketEvent]:
        """Reserve expired scoring claims for bounded recovery."""

    @abstractmethod
    async def mark_scored(
        self,
        event_id: UUID,
        claim_token: UUID,
        expected_version: int,
        score: int,
        completed_at: datetime,
    ) -> StateTransitionResult:
        """Complete a claimed scoring operation."""

    @abstractmethod
    async def mark_scoring_failed(
        self,
        event_id: UUID,
        claim_token: UUID,
        expected_version: int,
        error: ProcessingError,
        failed_at: datetime,
        next_retry_at: datetime | None,
    ) -> StateTransitionResult:
        """Record a scoring failure and optional retry eligibility."""

    @abstractmethod
    async def set_disposition(
        self,
        event_id: UUID,
        disposition: EventDisposition,
        changed_at: datetime,
        expected_version: int,
    ) -> StateTransitionResult:
        """Apply an administrative event disposition transition."""

    @abstractmethod
    async def release_claim(
        self,
        event_id: UUID,
        claim_token: UUID,
        expected_version: int,
        released_at: datetime,
        next_retry_at: datetime | None,
    ) -> StateTransitionResult:
        """Release a scoring claim after recoverable worker interruption."""


def event_immutable_signature(
    event: PriceDropMarketEvent,
) -> tuple[object, ...]:
    """Return immutable facts used to validate idempotent event creation."""
    return (
        event.identity_key,
        event.identity_version,
        event.event_type,
        event.marketplace,
        event.external_id,
        event.canonical_product_id,
        event.occurred_at,
        event.detected_at,
        event.payload,
    )
