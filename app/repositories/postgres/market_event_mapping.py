from __future__ import annotations

from typing import Any

from app.domain.lifecycle import EventDisposition, ScoringStatus
from app.domain.market_events import (
    MarketEvent,
    MarketEventType,
    PriceDropMarketEvent,
    PriceDropPayload,
    SnapshotIdentity,
)
from app.domain.processing import ProcessingError, WorkClaim
from app.models.market_event_record import MarketEventRecord
from app.models.price_snapshot_record import PriceSnapshotRecord


class UnsupportedPersistedMarketEventError(ValueError):
    """Raised when a stored event cannot be represented by the domain model."""


def market_event_values(
    event: PriceDropMarketEvent,
    *,
    previous_snapshot_id: int,
    current_snapshot_id: int,
) -> dict[str, Any]:
    """Map one immutable domain event to SQLAlchemy insert values."""
    claim = event.claim
    last_error = event.last_error
    return {
        "id": event.id,
        "identity_key": event.identity_key,
        "identity_version": event.identity_version,
        "identity_source": "snapshot_ids",
        "event_type": event.event_type.value,
        "marketplace": event.marketplace,
        "external_id": event.external_id,
        "canonical_product_id": event.canonical_product_id,
        "previous_snapshot_id": previous_snapshot_id,
        "current_snapshot_id": current_snapshot_id,
        "title": event.payload.title,
        "url": event.payload.url,
        "old_price": event.payload.old_price,
        "new_price": event.payload.new_price,
        "currency": event.payload.currency,
        "percentage": event.payload.percentage,
        "score": event.score,
        "disposition": event.disposition.value,
        "scoring_status": event.scoring_status.value,
        "scoring_attempt_count": event.scoring_attempt_count,
        "next_retry_at": event.next_retry_at,
        "claim_token": claim.token if claim is not None else None,
        "worker_id": claim.worker_id if claim is not None else None,
        "claimed_at": claim.claimed_at if claim is not None else None,
        "lease_expires_at": claim.lease_expires_at if claim is not None else None,
        "last_error_code": last_error.code if last_error is not None else None,
        "last_error_summary": (last_error.summary if last_error is not None else None),
        "occurred_at": event.occurred_at,
        "detected_at": event.detected_at,
        "created_at": event.created_at,
        "updated_at": event.created_at,
        "version": event.version,
        "audit_metadata": None,
    }


def market_event_to_domain(
    record: MarketEventRecord,
    previous_snapshot: PriceSnapshotRecord,
    current_snapshot: PriceSnapshotRecord,
) -> PriceDropMarketEvent:
    """Reconstruct an immutable domain event from explicit relational fields."""
    if record.event_type != MarketEventType.PRICE_DROP.value:
        msg = f"Unsupported persisted market event type: {record.event_type!r}."
        raise UnsupportedPersistedMarketEventError(msg)
    if record.identity_source != "snapshot_ids":
        msg = (
            "Unsupported persisted market event identity source: "
            f"{record.identity_source!r}."
        )
        raise UnsupportedPersistedMarketEventError(msg)
    if (
        record.previous_snapshot_id != previous_snapshot.id
        or record.current_snapshot_id != current_snapshot.id
    ):
        msg = "Persisted market event snapshot rows do not match its foreign keys."
        raise ValueError(msg)

    previous_identity = _snapshot_identity(previous_snapshot)
    current_identity = _snapshot_identity(current_snapshot)
    claim = _work_claim(record)
    last_error = _processing_error(record)
    payload = PriceDropPayload(
        title=record.title,
        url=record.url,
        old_price=record.old_price,
        new_price=record.new_price,
        currency=record.currency,
        absolute_difference=record.old_price - record.new_price,
        percentage=record.percentage,
        previous_snapshot=previous_identity,
        current_snapshot=current_identity,
    )
    return MarketEvent(
        id=record.id,
        identity_key=record.identity_key,
        identity_version=record.identity_version,
        event_type=MarketEventType.PRICE_DROP,
        marketplace=record.marketplace,
        external_id=record.external_id,
        canonical_product_id=record.canonical_product_id,
        occurred_at=record.occurred_at,
        detected_at=record.detected_at,
        payload=payload,
        created_at=record.created_at,
        disposition=EventDisposition(record.disposition),
        scoring_status=ScoringStatus(record.scoring_status),
        score=record.score,
        scoring_attempt_count=record.scoring_attempt_count,
        next_retry_at=record.next_retry_at,
        claim=claim,
        last_error=last_error,
        version=record.version,
    )


def _snapshot_identity(record: PriceSnapshotRecord) -> SnapshotIdentity:
    return SnapshotIdentity(
        marketplace=record.marketplace,
        external_id=record.external_id,
        collected_at=record.collected_at,
        price=record.price,
        currency=record.currency,
    )


def _work_claim(record: MarketEventRecord) -> WorkClaim | None:
    values = (
        record.claim_token,
        record.worker_id,
        record.claimed_at,
        record.lease_expires_at,
    )
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        msg = "Persisted market event contains an incomplete work claim."
        raise ValueError(msg)
    assert record.claim_token is not None
    assert record.worker_id is not None
    assert record.claimed_at is not None
    assert record.lease_expires_at is not None
    return WorkClaim(
        token=record.claim_token,
        worker_id=record.worker_id,
        claimed_at=record.claimed_at,
        lease_expires_at=record.lease_expires_at,
        version=record.version,
    )


def _processing_error(record: MarketEventRecord) -> ProcessingError | None:
    if record.last_error_code is None and record.last_error_summary is None:
        return None
    if record.last_error_code is None or record.last_error_summary is None:
        msg = "Persisted market event contains incomplete error details."
        raise ValueError(msg)
    return ProcessingError(
        code=record.last_error_code,
        summary=record.last_error_summary,
    )
