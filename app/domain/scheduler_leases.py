from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.identity import normalize_utc


@dataclass(slots=True, frozen=True, kw_only=True)
class SchedulerLease:
    """Durable ownership marker for one scheduler job execution slot."""

    job_name: str
    owner_id: str
    acquired_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        """Validate lease identity and UTC timestamps."""
        job_name = _require_text(self.job_name, field_name="job_name")
        owner_id = _require_text(self.owner_id, field_name="owner_id")
        acquired_at = normalize_utc(self.acquired_at, field_name="acquired_at")
        expires_at = normalize_utc(self.expires_at, field_name="expires_at")
        if expires_at <= acquired_at:
            msg = "Scheduler lease expiry must be after acquisition time."
            raise ValueError(msg)

        object.__setattr__(self, "job_name", job_name)
        object.__setattr__(self, "owner_id", owner_id)
        object.__setattr__(self, "acquired_at", acquired_at)
        object.__setattr__(self, "expires_at", expires_at)

    def is_active_at(self, now: datetime) -> bool:
        """Return whether the lease is still active at the provided UTC time."""
        return self.expires_at > normalize_utc(now, field_name="now")


def _require_text(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        msg = f"{field_name} must not be empty."
        raise ValueError(msg)
    if len(normalized) > 255:
        msg = f"{field_name} must not exceed 255 characters."
        raise ValueError(msg)
    return normalized
