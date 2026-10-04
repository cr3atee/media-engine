from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from uuid import UUID

from app.domain.admin_actions import AdminActorType, normalize_optional_reason
from app.domain.identity import normalize_utc, validate_sha256


class CanonicalOfferDecisionType(StrEnum):
    """Terminal review outcomes for one offer and canonical-product pair."""

    CONFIRMED = "confirmed"
    REJECTED = "rejected"


@dataclass(slots=True, frozen=True, kw_only=True)
class CanonicalOfferDecision:
    """Immutable audited review decision for one tenant-owned candidate pair."""

    id: UUID
    tenant_id: UUID
    marketplace: str
    external_id: str
    canonical_product_id: UUID
    decision: CanonicalOfferDecisionType
    actor_id: str
    actor_type: AdminActorType
    request_id: str
    idempotency_key: str
    request_fingerprint: str
    created_at: datetime
    reason: str | None = None

    def __post_init__(self) -> None:
        marketplace = _require_text(
            self.marketplace,
            field_name="marketplace",
            maximum_length=64,
        ).lower()
        external_id = _require_text(
            self.external_id,
            field_name="external_id",
            maximum_length=255,
        )
        actor_id = _require_text(
            self.actor_id,
            field_name="actor_id",
            maximum_length=128,
        )
        request_id = _require_text(
            self.request_id,
            field_name="request_id",
            maximum_length=128,
        )
        idempotency_key = _require_text(
            self.idempotency_key,
            field_name="idempotency_key",
            maximum_length=128,
        )
        validate_sha256(
            self.request_fingerprint,
            field_name="Canonical offer decision request fingerprint",
        )
        created_at = normalize_utc(self.created_at, field_name="created_at")
        object.__setattr__(self, "marketplace", marketplace)
        object.__setattr__(self, "external_id", external_id)
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "idempotency_key", idempotency_key)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "reason", normalize_optional_reason(self.reason))


def build_canonical_offer_decision_fingerprint(
    *,
    tenant_id: UUID,
    marketplace: str,
    external_id: str,
    canonical_product_id: UUID,
    decision: CanonicalOfferDecisionType,
    actor_id: str,
    actor_type: AdminActorType,
    reason: str | None,
) -> str:
    """Hash normalized review semantics independently from transport details."""
    payload = {
        "actor_id": _require_text(
            actor_id,
            field_name="actor_id",
            maximum_length=128,
        ),
        "actor_type": actor_type.value,
        "canonical_product_id": str(canonical_product_id),
        "decision": decision.value,
        "external_id": _require_text(
            external_id,
            field_name="external_id",
            maximum_length=255,
        ),
        "marketplace": _require_text(
            marketplace,
            field_name="marketplace",
            maximum_length=64,
        ).lower(),
        "reason": normalize_optional_reason(reason),
        "tenant_id": str(tenant_id),
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


def _require_text(value: str, *, field_name: str, maximum_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        msg = f"{field_name} must not be empty."
        raise ValueError(msg)
    if len(normalized) > maximum_length:
        msg = f"{field_name} must not exceed {maximum_length} characters."
        raise ValueError(msg)
    return normalized
