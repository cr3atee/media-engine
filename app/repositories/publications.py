from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from app.domain.processing import ProcessingError, StateTransitionResult
from app.domain.publications import (
    ClaimedPublication,
    CreatePublication,
    Publication,
    PublicationCreateResult,
)
from app.repositories.base import BaseRepository


class PublicationRepository(BaseRepository):
    """Async persistence contract for channel-independent publications."""

    @abstractmethod
    async def create_idempotently(
        self,
        command: CreatePublication,
    ) -> PublicationCreateResult:
        """Create a publication once by its deterministic identity."""

    @abstractmethod
    async def get_by_id(self, publication_id: UUID) -> Publication | None:
        """Return a publication by technical identifier."""

    @abstractmethod
    async def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> Publication | None:
        """Return a publication by deterministic delivery identity."""

    @abstractmethod
    async def list_for_event(self, event_id: UUID) -> Sequence[Publication]:
        """Return all publication records for one market event."""

    @abstractmethod
    async def list_pending(
        self,
        now: datetime,
        limit: int,
    ) -> Sequence[Publication]:
        """Return publications eligible for delivery."""

    @abstractmethod
    async def claim_pending(
        self,
        now: datetime,
        worker_id: str,
        lease_until: datetime,
        limit: int,
    ) -> Sequence[ClaimedPublication]:
        """Claim publications eligible for channel delivery."""

    @abstractmethod
    async def mark_published(
        self,
        publication_id: UUID,
        claim_token: UUID,
        expected_version: int,
        external_message_id: str,
        published_at: datetime,
    ) -> StateTransitionResult:
        """Record confirmed provider delivery."""

    @abstractmethod
    async def mark_failed(
        self,
        publication_id: UUID,
        claim_token: UUID,
        expected_version: int,
        error: ProcessingError,
        failed_at: datetime,
        next_retry_at: datetime | None,
    ) -> StateTransitionResult:
        """Record a known delivery failure and retry eligibility."""

    @abstractmethod
    async def mark_ambiguous(
        self,
        publication_id: UUID,
        claim_token: UUID,
        expected_version: int,
        error: ProcessingError,
        changed_at: datetime,
    ) -> StateTransitionResult:
        """Record an unknown provider outcome and block automatic resend."""

    @abstractmethod
    async def cancel(
        self,
        publication_id: UUID,
        changed_at: datetime,
        expected_version: int,
    ) -> StateTransitionResult:
        """Cancel an eligible unpublished delivery."""
