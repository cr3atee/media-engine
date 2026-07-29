from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.identity import normalize_utc


class IdempotentCreateStatus(StrEnum):
    """Outcome of an idempotent create operation."""

    CREATED = "created"
    EXISTING = "existing"


class StateTransitionOutcome(StrEnum):
    """Outcome of a guarded lifecycle transition."""

    APPLIED = "applied"
    NOT_FOUND = "not_found"
    INVALID_STATE = "invalid_state"
    CLAIM_LOST = "claim_lost"
    VERSION_CONFLICT = "version_conflict"


@dataclass(slots=True, frozen=True)
class ProcessingError:
    """Safe machine-readable processing failure details."""

    code: str
    summary: str

    def __post_init__(self) -> None:
        if not self.code.strip():
            msg = "Processing error code must not be empty."
            raise ValueError(msg)
        if not self.summary.strip():
            msg = "Processing error summary must not be empty."
            raise ValueError(msg)


@dataclass(slots=True, frozen=True)
class WorkClaim:
    """Database-independent ownership lease for one work item."""

    token: UUID
    worker_id: str
    claimed_at: datetime
    lease_expires_at: datetime
    version: int

    def __post_init__(self) -> None:
        if not self.worker_id.strip():
            msg = "Worker ID must not be empty."
            raise ValueError(msg)
        claimed_at = normalize_utc(self.claimed_at, field_name="claimed_at")
        lease_expires_at = normalize_utc(
            self.lease_expires_at,
            field_name="lease_expires_at",
        )
        if lease_expires_at <= claimed_at:
            msg = "Lease expiry must be later than claim time."
            raise ValueError(msg)
        if self.version < 1:
            msg = "Claim version must be positive."
            raise ValueError(msg)
        object.__setattr__(self, "claimed_at", claimed_at)
        object.__setattr__(self, "lease_expires_at", lease_expires_at)


@dataclass(slots=True, frozen=True)
class StateTransitionResult:
    """Typed result of a repository lifecycle update."""

    entity_id: UUID
    outcome: StateTransitionOutcome
    version: int | None = None

    @property
    def applied(self) -> bool:
        """Return whether the requested transition was persisted."""
        return self.outcome is StateTransitionOutcome.APPLIED
