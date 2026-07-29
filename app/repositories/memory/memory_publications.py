from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime
from uuid import UUID, uuid4

from app.domain.identity import normalize_utc
from app.domain.lifecycle import (
    InvalidLifecycleTransition,
    PublicationStatus,
    validate_publication_status_transition,
)
from app.domain.processing import (
    IdempotentCreateStatus,
    ProcessingError,
    StateTransitionOutcome,
    StateTransitionResult,
    WorkClaim,
)
from app.domain.publications import (
    ClaimedPublication,
    CreatePublication,
    Publication,
    PublicationCreateResult,
)
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.publications import PublicationRepository

type ClaimTokenFactory = Callable[[], UUID]

_EXPIRED_PUBLICATION_ERROR = ProcessingError(
    code="lease_expired_ambiguous",
    summary="Publication claim expired before delivery was confirmed.",
)


class MemoryPublicationRepository(PublicationRepository):
    """Deterministic in-memory persistence for publication lifecycles."""

    def __init__(
        self,
        *,
        claim_token_factory: ClaimTokenFactory = uuid4,
    ) -> None:
        """Initialize isolated storage and an injectable claim-token source."""
        self._publications_by_id: dict[UUID, Publication] = {}
        self._publication_ids_by_key: dict[str, UUID] = {}
        self._claim_token_factory = claim_token_factory

    async def create_idempotently(
        self,
        command: CreatePublication,
    ) -> PublicationCreateResult:
        """Create one logical delivery and preserve its first scheduling facts."""
        existing_id = self._publication_ids_by_key.get(command.idempotency_key)
        if existing_id is not None:
            return PublicationCreateResult(
                publication=self._publications_by_id[existing_id],
                status=IdempotentCreateStatus.EXISTING,
            )

        existing = self._publications_by_id.get(command.id)
        if existing is not None:
            msg = (
                "Publication ID already belongs to idempotency key "
                f"{existing.idempotency_key}."
            )
            raise RepositoryIdentityConflictError(msg)

        publication = Publication(
            id=command.id,
            event_id=command.event_id,
            content_id=command.content_id,
            channel=command.channel,
            destination_key=command.destination_key,
            idempotency_key=command.idempotency_key,
            status=PublicationStatus.PENDING,
            attempt_count=0,
            scheduled_at=command.scheduled_at,
            created_at=command.created_at,
            updated_at=command.created_at,
        )
        self._store(publication)
        return PublicationCreateResult(
            publication=publication,
            status=IdempotentCreateStatus.CREATED,
        )

    async def get_by_id(self, publication_id: UUID) -> Publication | None:
        """Return one immutable publication snapshot by identifier."""
        return self._publications_by_id.get(publication_id)

    async def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> Publication | None:
        """Return one immutable publication snapshot by delivery identity."""
        publication_id = self._publication_ids_by_key.get(idempotency_key)
        if publication_id is None:
            return None
        return self._publications_by_id[publication_id]

    async def list_for_event(self, event_id: UUID) -> Sequence[Publication]:
        """List an event's publications by delivery readiness and stable ID."""
        return tuple(
            sorted(
                (
                    publication
                    for publication in self._publications_by_id.values()
                    if publication.event_id == event_id
                ),
                key=_publication_processing_order,
            ),
        )

    async def list_pending(
        self,
        now: datetime,
        limit: int,
    ) -> Sequence[Publication]:
        """List due pending or known-failure retry work deterministically."""
        now = normalize_utc(now, field_name="now")
        _validate_limit(limit)
        eligible = (
            publication
            for publication in self._publications_by_id.values()
            if _is_publication_claimable(publication, now)
        )
        return tuple(
            sorted(eligible, key=_publication_processing_order)[:limit],
        )

    async def claim_pending(
        self,
        now: datetime,
        worker_id: str,
        lease_until: datetime,
        limit: int,
    ) -> Sequence[ClaimedPublication]:
        """Claim due deliveries and quarantine expired unknown outcomes."""
        now, lease_until, worker_id = _validate_claim_request(
            now,
            lease_until,
            worker_id,
        )
        _validate_limit(limit)
        self._mark_expired_claims_ambiguous(now)
        eligible = sorted(
            (
                publication
                for publication in self._publications_by_id.values()
                if _is_publication_claimable(publication, now)
            ),
            key=_publication_processing_order,
        )[:limit]
        claimed: list[ClaimedPublication] = []

        for publication in eligible:
            if publication.status is PublicationStatus.FAILED:
                validate_publication_status_transition(
                    PublicationStatus.FAILED,
                    PublicationStatus.PENDING,
                )
                validate_publication_status_transition(
                    PublicationStatus.PENDING,
                    PublicationStatus.IN_PROGRESS,
                )
            else:
                validate_publication_status_transition(
                    publication.status,
                    PublicationStatus.IN_PROGRESS,
                )

            next_version = publication.version + 1
            claim = WorkClaim(
                token=self._claim_token_factory(),
                worker_id=worker_id,
                claimed_at=now,
                lease_expires_at=lease_until,
                version=next_version,
            )
            updated = replace(
                publication,
                status=PublicationStatus.IN_PROGRESS,
                attempt_count=publication.attempt_count + 1,
                updated_at=now,
                next_retry_at=None,
                claim=claim,
                last_error=None,
                version=next_version,
            )
            self._store(updated)
            claimed.append(ClaimedPublication(publication=updated, claim=claim))

        return tuple(claimed)

    async def mark_published(
        self,
        publication_id: UUID,
        claim_token: UUID,
        expected_version: int,
        external_message_id: str,
        published_at: datetime,
    ) -> StateTransitionResult:
        """Persist confirmed delivery, treating exact duplicate success as applied."""
        published_at = normalize_utc(published_at, field_name="published_at")
        external_message_id = external_message_id.strip()
        if not external_message_id:
            msg = "External message ID must not be empty."
            raise ValueError(msg)

        publication = self._publications_by_id.get(publication_id)
        if (
            publication is not None
            and publication.status is PublicationStatus.PUBLISHED
        ):
            if publication.external_message_id == external_message_id:
                return _applied(publication.id, publication.version)
            return _transition_result(
                publication.id,
                StateTransitionOutcome.INVALID_STATE,
                publication.version,
            )

        guarded = _guard_publication_claim(
            publication_id,
            publication,
            claim_token,
            expected_version,
        )
        if guarded is not None:
            return guarded
        assert publication is not None
        validate_publication_status_transition(
            publication.status,
            PublicationStatus.PUBLISHED,
        )
        updated = replace(
            publication,
            status=PublicationStatus.PUBLISHED,
            external_message_id=external_message_id,
            published_at=published_at,
            updated_at=published_at,
            next_retry_at=None,
            claim=None,
            last_error=None,
            version=publication.version + 1,
        )
        self._store(updated)
        return _applied(updated.id, updated.version)

    async def mark_failed(
        self,
        publication_id: UUID,
        claim_token: UUID,
        expected_version: int,
        error: ProcessingError,
        failed_at: datetime,
        next_retry_at: datetime | None,
    ) -> StateTransitionResult:
        """Persist a known failed delivery and optional retry eligibility."""
        failed_at = normalize_utc(failed_at, field_name="failed_at")
        next_retry_at = _normalize_optional_utc(
            next_retry_at,
            field_name="next_retry_at",
        )
        publication = self._publications_by_id.get(publication_id)
        guarded = _guard_publication_claim(
            publication_id,
            publication,
            claim_token,
            expected_version,
        )
        if guarded is not None:
            return guarded
        assert publication is not None
        validate_publication_status_transition(
            publication.status,
            PublicationStatus.FAILED,
        )
        updated = replace(
            publication,
            status=PublicationStatus.FAILED,
            updated_at=failed_at,
            next_retry_at=next_retry_at,
            claim=None,
            last_error=error,
            version=publication.version + 1,
        )
        self._store(updated)
        return _applied(updated.id, updated.version)

    async def mark_ambiguous(
        self,
        publication_id: UUID,
        claim_token: UUID,
        expected_version: int,
        error: ProcessingError,
        changed_at: datetime,
    ) -> StateTransitionResult:
        """Block automatic resend when provider acceptance is unknown."""
        changed_at = normalize_utc(changed_at, field_name="changed_at")
        publication = self._publications_by_id.get(publication_id)
        guarded = _guard_publication_claim(
            publication_id,
            publication,
            claim_token,
            expected_version,
        )
        if guarded is not None:
            return guarded
        assert publication is not None
        validate_publication_status_transition(
            publication.status,
            PublicationStatus.AMBIGUOUS,
        )
        updated = replace(
            publication,
            status=PublicationStatus.AMBIGUOUS,
            updated_at=changed_at,
            next_retry_at=None,
            claim=None,
            last_error=error,
            version=publication.version + 1,
        )
        self._store(updated)
        return _applied(updated.id, updated.version)

    async def cancel(
        self,
        publication_id: UUID,
        changed_at: datetime,
        expected_version: int,
    ) -> StateTransitionResult:
        """Cancel an eligible unpublished delivery with optimistic guarding."""
        changed_at = normalize_utc(changed_at, field_name="changed_at")
        publication = self._publications_by_id.get(publication_id)
        guarded = _guard_version(publication_id, publication, expected_version)
        if guarded is not None:
            return guarded
        assert publication is not None
        try:
            validate_publication_status_transition(
                publication.status,
                PublicationStatus.CANCELLED,
            )
        except InvalidLifecycleTransition:
            return _transition_result(
                publication.id,
                StateTransitionOutcome.INVALID_STATE,
                publication.version,
            )
        updated = replace(
            publication,
            status=PublicationStatus.CANCELLED,
            updated_at=changed_at,
            next_retry_at=None,
            claim=None,
            version=publication.version + 1,
        )
        self._store(updated)
        return _applied(updated.id, updated.version)

    def _mark_expired_claims_ambiguous(self, now: datetime) -> None:
        expired = (
            publication
            for publication in tuple(self._publications_by_id.values())
            if publication.status is PublicationStatus.IN_PROGRESS
            and publication.claim is not None
            and publication.claim.lease_expires_at <= now
        )
        for publication in expired:
            updated = replace(
                publication,
                status=PublicationStatus.AMBIGUOUS,
                updated_at=now,
                next_retry_at=None,
                claim=None,
                last_error=_EXPIRED_PUBLICATION_ERROR,
                version=publication.version + 1,
            )
            self._store(updated)

    def _store(self, publication: Publication) -> None:
        self._publications_by_id[publication.id] = publication
        self._publication_ids_by_key[publication.idempotency_key] = publication.id


def _is_publication_claimable(publication: Publication, now: datetime) -> bool:
    scheduled = publication.scheduled_at is None or publication.scheduled_at <= now
    if not scheduled:
        return False
    if publication.status is PublicationStatus.PENDING:
        return publication.next_retry_at is None or publication.next_retry_at <= now
    if publication.status is PublicationStatus.FAILED:
        return (
            publication.next_retry_at is not None and publication.next_retry_at <= now
        )
    return False


def _publication_processing_order(
    publication: Publication,
) -> tuple[datetime, datetime, str]:
    ready_at = (
        publication.next_retry_at or publication.scheduled_at or publication.created_at
    )
    return (ready_at, publication.created_at, publication.id.hex)


def _guard_publication_claim(
    publication_id: UUID,
    publication: Publication | None,
    claim_token: UUID,
    expected_version: int,
) -> StateTransitionResult | None:
    guarded = _guard_version(publication_id, publication, expected_version)
    if guarded is not None:
        return guarded
    assert publication is not None
    if (
        publication.status is not PublicationStatus.IN_PROGRESS
        or publication.claim is None
    ):
        return _transition_result(
            publication.id,
            StateTransitionOutcome.INVALID_STATE,
            publication.version,
        )
    if publication.claim.token != claim_token:
        return _transition_result(
            publication.id,
            StateTransitionOutcome.CLAIM_LOST,
            publication.version,
        )
    return None


def _guard_version(
    entity_id: UUID,
    publication: Publication | None,
    expected_version: int,
) -> StateTransitionResult | None:
    if publication is None:
        return _transition_result(
            entity_id,
            StateTransitionOutcome.NOT_FOUND,
            None,
        )
    if publication.version != expected_version:
        return _transition_result(
            entity_id,
            StateTransitionOutcome.VERSION_CONFLICT,
            publication.version,
        )
    return None


def _validate_claim_request(
    now: datetime,
    lease_until: datetime,
    worker_id: str,
) -> tuple[datetime, datetime, str]:
    now = normalize_utc(now, field_name="now")
    lease_until = normalize_utc(lease_until, field_name="lease_until")
    worker_id = worker_id.strip()
    if not worker_id:
        msg = "Worker ID must not be empty."
        raise ValueError(msg)
    if lease_until <= now:
        msg = "Lease expiry must be later than claim time."
        raise ValueError(msg)
    return now, lease_until, worker_id


def _validate_limit(limit: int) -> None:
    if limit < 0:
        msg = "Repository limit must not be negative."
        raise ValueError(msg)


def _normalize_optional_utc(
    value: datetime | None,
    *,
    field_name: str,
) -> datetime | None:
    return normalize_utc(value, field_name=field_name) if value is not None else None


def _applied(entity_id: UUID, version: int) -> StateTransitionResult:
    return _transition_result(entity_id, StateTransitionOutcome.APPLIED, version)


def _transition_result(
    entity_id: UUID,
    outcome: StateTransitionOutcome,
    version: int | None,
) -> StateTransitionResult:
    return StateTransitionResult(entity_id=entity_id, outcome=outcome, version=version)
