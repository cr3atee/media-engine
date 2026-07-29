from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from app.domain.identity import (
    canonicalize_decimal,
    canonicalize_identity_fields,
    canonicalize_utc,
    hash_identity_fields,
    normalize_utc,
    validate_sha256,
)
from app.domain.lifecycle import EventDisposition, ScoringStatus
from app.domain.price_snapshot import PriceSnapshot
from app.domain.processing import (
    IdempotentCreateStatus,
    ProcessingError,
    WorkClaim,
)

CURRENT_EVENT_IDENTITY_VERSION = 1
_SUPPORTED_EVENT_IDENTITY_VERSIONS = frozenset({CURRENT_EVENT_IDENTITY_VERSION})


class UnsupportedEventIdentityVersion(ValueError):
    """Raised when an event identity algorithm version is unsupported."""


class MarketEventType(StrEnum):
    """Stable market-event type values used by event identity."""

    PRICE_DROP = "price_drop"


class EventPayload(Protocol):
    """Serialization boundary implemented by typed market-event payloads."""

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic serialization-safe mapping."""
        ...


@dataclass(slots=True, frozen=True)
class SnapshotIdentity:
    """Exact database-independent identity of an observed price snapshot."""

    marketplace: str
    external_id: str
    collected_at: datetime
    price: Decimal
    currency: str

    def __post_init__(self) -> None:
        marketplace = _normalize_marketplace(self.marketplace)
        external_id = _require_text(self.external_id, field_name="external_id")
        currency = _normalize_currency(self.currency)
        collected_at = normalize_utc(self.collected_at, field_name="collected_at")
        _validate_money(self.price, field_name="price")
        object.__setattr__(self, "marketplace", marketplace)
        object.__setattr__(self, "external_id", external_id)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "collected_at", collected_at)

    @classmethod
    def from_snapshot(cls, snapshot: PriceSnapshot) -> SnapshotIdentity:
        """Build an identity from an existing domain price snapshot."""
        return cls(
            marketplace=snapshot.marketplace,
            external_id=snapshot.external_id,
            collected_at=snapshot.collected_at,
            price=snapshot.price,
            currency=snapshot.currency,
        )

    def canonical_value(self) -> str:
        """Return the canonical snapshot value used by event identity."""
        return canonicalize_identity_fields(
            self.marketplace,
            self.external_id,
            canonicalize_utc(self.collected_at),
            canonicalize_decimal(self.price),
            self.currency,
        )

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic serialization-safe mapping."""
        return {
            "marketplace": self.marketplace,
            "external_id": self.external_id,
            "collected_at": canonicalize_utc(self.collected_at),
            "price": canonicalize_decimal(self.price),
            "currency": self.currency,
        }


@dataclass(slots=True, frozen=True)
class EventIdentity:
    """Versioned deterministic identity assigned to a market event."""

    key: str
    version: int

    def __post_init__(self) -> None:
        _validate_event_identity_version(self.version)
        validate_sha256(self.key, field_name="Event identity key")


@dataclass(slots=True, frozen=True)
class PriceDropPayload:
    """Typed immutable facts describing one observed price drop."""

    title: str | None
    url: str | None
    old_price: Decimal
    new_price: Decimal
    currency: str
    absolute_difference: Decimal
    percentage: Decimal
    previous_snapshot: SnapshotIdentity
    current_snapshot: SnapshotIdentity

    def __post_init__(self) -> None:
        _validate_optional_text(self.title, field_name="title")
        _validate_optional_text(self.url, field_name="url")
        _validate_money(self.old_price, field_name="old_price")
        _validate_money(self.new_price, field_name="new_price")
        _validate_decimal(self.absolute_difference, field_name="absolute_difference")
        _validate_decimal(self.percentage, field_name="percentage")

        currency = _normalize_currency(self.currency)
        if self.new_price >= self.old_price:
            msg = "Price-drop payload requires new_price to be lower than old_price."
            raise ValueError(msg)
        if self.absolute_difference != self.old_price - self.new_price:
            msg = "absolute_difference must equal old_price minus new_price."
            raise ValueError(msg)
        if self.percentage < 0:
            msg = "Price-drop percentage must not be negative."
            raise ValueError(msg)
        if self.previous_snapshot.price != self.old_price:
            msg = "Previous snapshot price must equal old_price."
            raise ValueError(msg)
        if self.current_snapshot.price != self.new_price:
            msg = "Current snapshot price must equal new_price."
            raise ValueError(msg)
        if self.previous_snapshot.currency != currency:
            msg = "Previous snapshot currency must match payload currency."
            raise ValueError(msg)
        if self.current_snapshot.currency != currency:
            msg = "Current snapshot currency must match payload currency."
            raise ValueError(msg)
        if self.previous_snapshot.marketplace != self.current_snapshot.marketplace:
            msg = "Price-drop snapshots must belong to the same marketplace."
            raise ValueError(msg)
        if self.previous_snapshot.external_id != self.current_snapshot.external_id:
            msg = "Price-drop snapshots must belong to the same external offer."
            raise ValueError(msg)
        if self.current_snapshot.collected_at < self.previous_snapshot.collected_at:
            msg = "Current snapshot must not predate the previous snapshot."
            raise ValueError(msg)
        object.__setattr__(self, "currency", currency)

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic serialization-safe mapping."""
        return {
            "title": self.title,
            "url": self.url,
            "old_price": canonicalize_decimal(self.old_price),
            "new_price": canonicalize_decimal(self.new_price),
            "currency": self.currency,
            "absolute_difference": canonicalize_decimal(self.absolute_difference),
            "percentage": canonicalize_decimal(self.percentage),
            "previous_snapshot": self.previous_snapshot.to_dict(),
            "current_snapshot": self.current_snapshot.to_dict(),
        }


@dataclass(slots=True, frozen=True, kw_only=True)
class MarketEvent[TEventPayload: EventPayload]:
    """Immutable typed envelope for a durable market event."""

    identity_key: str
    identity_version: int
    event_type: MarketEventType
    marketplace: str
    external_id: str
    occurred_at: datetime
    detected_at: datetime
    payload: TEventPayload
    id: UUID = field(default_factory=uuid4)
    canonical_product_id: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    disposition: EventDisposition = EventDisposition.ACTIVE
    scoring_status: ScoringStatus = ScoringStatus.PENDING
    score: int | None = None
    scoring_attempt_count: int = 0
    next_retry_at: datetime | None = None
    claim: WorkClaim | None = None
    last_error: ProcessingError | None = None
    version: int = 1

    def __post_init__(self) -> None:
        marketplace = _normalize_marketplace(self.marketplace)
        external_id = _require_text(self.external_id, field_name="external_id")
        occurred_at = normalize_utc(self.occurred_at, field_name="occurred_at")
        detected_at = normalize_utc(self.detected_at, field_name="detected_at")
        created_at = normalize_utc(self.created_at, field_name="created_at")
        next_retry_at = (
            normalize_utc(self.next_retry_at, field_name="next_retry_at")
            if self.next_retry_at is not None
            else None
        )

        if self.event_type is not MarketEventType.PRICE_DROP:
            msg = f"Unsupported market event type: {self.event_type!r}."
            raise ValueError(msg)
        if not isinstance(self.payload, PriceDropPayload):
            msg = "price_drop events require PriceDropPayload."
            raise TypeError(msg)
        if marketplace != self.payload.current_snapshot.marketplace:
            msg = "Event marketplace must match its snapshot identities."
            raise ValueError(msg)
        if external_id != self.payload.current_snapshot.external_id:
            msg = "Event external ID must match its snapshot identities."
            raise ValueError(msg)
        if occurred_at != self.payload.current_snapshot.collected_at:
            msg = "Event occurred_at must equal the current snapshot timestamp."
            raise ValueError(msg)
        if detected_at < occurred_at:
            msg = "Event detection time must not predate occurrence time."
            raise ValueError(msg)
        if created_at < detected_at:
            msg = "Event creation time must not predate detection time."
            raise ValueError(msg)
        if self.scoring_attempt_count < 0:
            msg = "Scoring attempt count must not be negative."
            raise ValueError(msg)
        if self.version < 1:
            msg = "Event version must be positive."
            raise ValueError(msg)
        if self.score is not None and not 0 <= self.score <= 100:
            msg = "Event score must be between 0 and 100."
            raise ValueError(msg)
        if self.scoring_status is ScoringStatus.SUCCEEDED and self.score is None:
            msg = "Succeeded scoring status requires a score."
            raise ValueError(msg)
        if (
            self.score is not None
            and self.scoring_status is not ScoringStatus.SUCCEEDED
        ):
            msg = "A score is valid only when scoring has succeeded."
            raise ValueError(msg)
        if self.scoring_status is ScoringStatus.IN_PROGRESS and self.claim is None:
            msg = "In-progress scoring requires a work claim."
            raise ValueError(msg)
        if (
            self.claim is not None
            and self.scoring_status is not ScoringStatus.IN_PROGRESS
        ):
            msg = "A scoring claim is valid only while scoring is in progress."
            raise ValueError(msg)

        identity = build_event_identity(
            event_type=self.event_type,
            marketplace=marketplace,
            external_id=external_id,
            previous_snapshot=self.payload.previous_snapshot,
            current_snapshot=self.payload.current_snapshot,
            identity_version=self.identity_version,
        )
        if self.identity_key != identity.key:
            msg = "Event identity key does not match its immutable identity inputs."
            raise ValueError(msg)

        object.__setattr__(self, "marketplace", marketplace)
        object.__setattr__(self, "external_id", external_id)
        object.__setattr__(self, "occurred_at", occurred_at)
        object.__setattr__(self, "detected_at", detected_at)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "next_retry_at", next_retry_at)

    @property
    def title(self) -> str | None:
        """Return the title captured by the typed payload."""
        if isinstance(self.payload, PriceDropPayload):
            return self.payload.title
        return None

    @property
    def url(self) -> str | None:
        """Return the URL captured by the typed payload."""
        return self.payload.url if isinstance(self.payload, PriceDropPayload) else None

    @property
    def previous_snapshot(self) -> SnapshotIdentity:
        """Return the previous source snapshot identity."""
        if isinstance(self.payload, PriceDropPayload):
            return self.payload.previous_snapshot
        msg = "Event payload does not expose a previous snapshot."
        raise TypeError(msg)

    @property
    def current_snapshot(self) -> SnapshotIdentity:
        """Return the current source snapshot identity."""
        if isinstance(self.payload, PriceDropPayload):
            return self.payload.current_snapshot
        msg = "Event payload does not expose a current snapshot."
        raise TypeError(msg)

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic serialization-safe mapping."""
        return {
            "id": str(self.id),
            "identity_key": self.identity_key,
            "identity_version": self.identity_version,
            "event_type": self.event_type.value,
            "marketplace": self.marketplace,
            "external_id": self.external_id,
            "canonical_product_id": (
                str(self.canonical_product_id)
                if self.canonical_product_id is not None
                else None
            ),
            "occurred_at": canonicalize_utc(self.occurred_at),
            "detected_at": canonicalize_utc(self.detected_at),
            "created_at": canonicalize_utc(self.created_at),
            "payload": self.payload.to_dict(),
            "disposition": self.disposition.value,
            "scoring_status": self.scoring_status.value,
            "score": self.score,
            "scoring_attempt_count": self.scoring_attempt_count,
            "next_retry_at": (
                canonicalize_utc(self.next_retry_at)
                if self.next_retry_at is not None
                else None
            ),
            "version": self.version,
        }


type PriceDropMarketEvent = MarketEvent[PriceDropPayload]


@dataclass(slots=True, frozen=True)
class MarketEventCandidate:
    """Idempotent persistence input for one fully identified event."""

    event: PriceDropMarketEvent


@dataclass(slots=True, frozen=True)
class EventAddResult:
    """Result of adding an event by deterministic identity."""

    event: PriceDropMarketEvent
    status: IdempotentCreateStatus

    @property
    def created(self) -> bool:
        """Return whether the event was newly created."""
        return self.status is IdempotentCreateStatus.CREATED

    @property
    def identity_version(self) -> int:
        """Return the identity version retained by the event."""
        return self.event.identity_version


@dataclass(slots=True, frozen=True)
class ClaimedMarketEvent:
    """Market event paired with the repository claim that owns it."""

    event: PriceDropMarketEvent
    claim: WorkClaim


def build_event_identity(
    *,
    event_type: MarketEventType | str,
    marketplace: str,
    external_id: str,
    previous_snapshot: SnapshotIdentity,
    current_snapshot: SnapshotIdentity,
    identity_version: int = CURRENT_EVENT_IDENTITY_VERSION,
) -> EventIdentity:
    """Build the versioned deterministic identity for a market event."""
    _validate_event_identity_version(identity_version)
    event_type_value = (
        event_type.value if isinstance(event_type, MarketEventType) else event_type
    )
    event_type_value = _require_text(event_type_value, field_name="event_type")
    marketplace = _normalize_marketplace(marketplace)
    external_id = _require_text(external_id, field_name="external_id")
    if previous_snapshot.marketplace != marketplace:
        msg = "Previous snapshot marketplace must match event marketplace."
        raise ValueError(msg)
    if current_snapshot.marketplace != marketplace:
        msg = "Current snapshot marketplace must match event marketplace."
        raise ValueError(msg)
    if previous_snapshot.external_id != external_id:
        msg = "Previous snapshot external ID must match event external ID."
        raise ValueError(msg)
    if current_snapshot.external_id != external_id:
        msg = "Current snapshot external ID must match event external ID."
        raise ValueError(msg)

    return EventIdentity(
        key=hash_identity_fields(
            f"v{identity_version}",
            event_type_value,
            marketplace,
            external_id,
            previous_snapshot.canonical_value(),
            current_snapshot.canonical_value(),
        ),
        version=identity_version,
    )


def create_price_drop_market_event(
    *,
    payload: PriceDropPayload,
    detected_at: datetime,
    event_id: UUID | None = None,
    canonical_product_id: UUID | None = None,
    created_at: datetime | None = None,
) -> PriceDropMarketEvent:
    """Create a fully identified price-drop market event."""
    identity = build_event_identity(
        event_type=MarketEventType.PRICE_DROP,
        marketplace=payload.current_snapshot.marketplace,
        external_id=payload.current_snapshot.external_id,
        previous_snapshot=payload.previous_snapshot,
        current_snapshot=payload.current_snapshot,
    )
    return MarketEvent(
        id=event_id or uuid4(),
        identity_key=identity.key,
        identity_version=identity.version,
        event_type=MarketEventType.PRICE_DROP,
        marketplace=payload.current_snapshot.marketplace,
        external_id=payload.current_snapshot.external_id,
        canonical_product_id=canonical_product_id,
        occurred_at=payload.current_snapshot.collected_at,
        detected_at=detected_at,
        payload=payload,
        created_at=created_at or datetime.now(UTC),
    )


def _validate_event_identity_version(version: int) -> None:
    if version not in _SUPPORTED_EVENT_IDENTITY_VERSIONS:
        msg = f"Unsupported event identity version: {version}."
        raise UnsupportedEventIdentityVersion(msg)


def _normalize_marketplace(value: str) -> str:
    return _require_text(value, field_name="marketplace").lower()


def _normalize_currency(value: str) -> str:
    return _require_text(value, field_name="currency").upper()


def _require_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        msg = f"{field_name} must not be empty."
        raise ValueError(msg)
    return value.strip()


def _validate_optional_text(value: str | None, *, field_name: str) -> None:
    if value is not None and not value.strip():
        msg = f"{field_name} must be non-empty when provided."
        raise ValueError(msg)


def _validate_decimal(value: Decimal, *, field_name: str) -> None:
    if not isinstance(value, Decimal):
        msg = f"{field_name} must use Decimal."
        raise TypeError(msg)
    if not value.is_finite():
        msg = f"{field_name} must be finite."
        raise ValueError(msg)


def _validate_money(value: Decimal, *, field_name: str) -> None:
    _validate_decimal(value, field_name=field_name)
    if value < 0:
        msg = f"{field_name} must not be negative."
        raise ValueError(msg)
