from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from app.domain.identity import normalize_utc
from app.domain.processing import ProcessingError, StateTransitionOutcome
from app.domain.publications import (
    CreatePublication,
    PublicationCreateResult,
)
from app.repositories.publications import PublicationRepository
from app.services.repository_scope import RepositoryScopeFactory

type PublicationIdFactory = Callable[[], UUID]

_EXPIRED_PUBLICATION_ERROR = ProcessingError(
    code="lease_expired_ambiguous",
    summary="Publication claim expired before delivery was confirmed.",
)


@dataclass(slots=True, frozen=True)
class PublicationTarget:
    """Channel-independent destination for a future delivery adapter."""

    channel: str
    destination_key: str

    def __post_init__(self) -> None:
        channel = self.channel.strip().lower()
        destination_key = self.destination_key.strip()
        if not channel or not destination_key:
            msg = "Publication channel and destination key must not be empty."
            raise ValueError(msg)
        object.__setattr__(self, "channel", channel)
        object.__setattr__(self, "destination_key", destination_key)


@dataclass(slots=True, frozen=True)
class PublicationRecoveryResult:
    """Immutable result of one bounded publication-claim recovery run."""

    requested_limit: int
    expired_found: int
    ambiguous: int
    conflicts: int


class PublicationIntentService:
    """Create durable delivery intent and recover unknown delivery outcomes."""

    def __init__(
        self,
        *,
        repository_scope_factory: RepositoryScopeFactory,
        publication_id_factory: PublicationIdFactory = uuid4,
    ) -> None:
        """Configure transaction scopes and publication identity generation."""
        self._repository_scope_factory = repository_scope_factory
        self._publication_id_factory = publication_id_factory

    async def create(
        self,
        repository: PublicationRepository,
        *,
        event_id: UUID,
        content_id: UUID,
        target: PublicationTarget,
        created_at: datetime,
    ) -> PublicationCreateResult:
        """Create one idempotent intent inside the caller-owned transaction."""
        created_at = normalize_utc(created_at, field_name="created_at")
        return await repository.create_idempotently(
            CreatePublication(
                id=self._publication_id_factory(),
                event_id=event_id,
                content_id=content_id,
                channel=target.channel,
                destination_key=target.destination_key,
                created_at=created_at,
            )
        )

    async def recover_stale_publication_claims(
        self,
        *,
        limit: int,
        now: datetime,
    ) -> PublicationRecoveryResult:
        """Move expired delivery claims to protected ambiguous state once."""
        now = normalize_utc(now, field_name="now")
        _validate_limit(limit)
        applied = 0
        conflicts = 0
        async with self._repository_scope_factory() as repositories:
            expired = await repositories.publications.list_expired_claims(now, limit)
            for claimed in expired:
                transition = await repositories.publications.mark_ambiguous(
                    claimed.publication.id,
                    claimed.claim.token,
                    claimed.publication.version,
                    _EXPIRED_PUBLICATION_ERROR,
                    now,
                )
                if transition.outcome is StateTransitionOutcome.APPLIED:
                    applied += 1
                else:
                    conflicts += 1
        return PublicationRecoveryResult(
            requested_limit=limit,
            expired_found=len(expired),
            ambiguous=applied,
            conflicts=conflicts,
        )


def _validate_limit(limit: int) -> None:
    if limit < 0:
        msg = "Publication recovery limit must not be negative."
        raise ValueError(msg)
