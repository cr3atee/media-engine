from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from app.domain.generated_content import (
    ClaimedContentAttempt,
    ContentCreateResult,
    CreateContentAttempt,
    GeneratedContentAttempt,
)
from app.domain.lifecycle import ContentReviewStatus
from app.domain.processing import ProcessingError, StateTransitionResult
from app.repositories.base import BaseRepository


class GeneratedContentRepository(BaseRepository):
    """Async persistence contract for immutable generated-content revisions."""

    @abstractmethod
    async def create_attempt(
        self,
        command: CreateContentAttempt,
    ) -> ContentCreateResult:
        """Create one content attempt idempotently."""

    @abstractmethod
    async def get_by_id(
        self,
        content_id: UUID,
    ) -> GeneratedContentAttempt | None:
        """Return a content attempt by identifier."""

    @abstractmethod
    async def list_for_event(
        self,
        event_id: UUID,
    ) -> Sequence[GeneratedContentAttempt]:
        """Return immutable content revisions for one event."""

    @abstractmethod
    async def get_latest_revision(
        self,
        event_id: UUID,
        content_type: str,
        language: str,
    ) -> GeneratedContentAttempt | None:
        """Return the latest revision for an event and content format."""

    @abstractmethod
    async def claim_pending(
        self,
        now: datetime,
        worker_id: str,
        lease_until: datetime,
        limit: int,
    ) -> Sequence[ClaimedContentAttempt]:
        """Claim content attempts eligible for generation."""

    @abstractmethod
    async def complete_attempt(
        self,
        content_id: UUID,
        claim_token: UUID,
        expected_version: int,
        content_text: str,
        content_checksum: str,
        completed_at: datetime,
    ) -> StateTransitionResult:
        """Complete one claimed content-generation attempt."""

    @abstractmethod
    async def fail_attempt(
        self,
        content_id: UUID,
        claim_token: UUID,
        expected_version: int,
        error: ProcessingError,
        failed_at: datetime,
        next_retry_at: datetime | None,
    ) -> StateTransitionResult:
        """Record a terminal generation attempt failure."""

    @abstractmethod
    async def set_review_status(
        self,
        content_id: UUID,
        review_status: ContentReviewStatus,
        changed_at: datetime,
        expected_version: int,
    ) -> StateTransitionResult:
        """Apply an administrative content-review transition."""

    @abstractmethod
    async def release_claim(
        self,
        content_id: UUID,
        claim_token: UUID,
        expected_version: int,
        released_at: datetime,
    ) -> StateTransitionResult:
        """Abandon an expired or interrupted content-generation claim."""
