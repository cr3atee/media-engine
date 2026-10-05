from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import Field, field_validator

from app.api.schemas.common import ApiModel
from app.domain.admin_actions import AdminActorType
from app.domain.canonical_offer_decisions import CanonicalOfferDecisionType
from app.matching.confidence import MatchDecision


def _nonempty_text(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("Value must not be blank.")
    return normalized


def _optional_nonempty_text(value: str | None) -> str | None:
    if value is None:
        return None
    return _nonempty_text(value)


class ConfirmCanonicalOfferRequest(ApiModel):
    """Input for confirming one canonical offer candidate."""

    marketplace: str = Field(min_length=1, max_length=64)
    external_id: str = Field(min_length=1, max_length=255)
    canonical_product_id: UUID
    reason: str | None = Field(default=None, max_length=2000)

    _normalize_marketplace = field_validator("marketplace")(_nonempty_text)
    _normalize_external_id = field_validator("external_id")(_nonempty_text)
    _normalize_reason = field_validator("reason")(_optional_nonempty_text)


class RejectCanonicalOfferRequest(ApiModel):
    """Input for rejecting one canonical offer candidate with evidence."""

    marketplace: str = Field(min_length=1, max_length=64)
    external_id: str = Field(min_length=1, max_length=255)
    canonical_product_id: UUID
    reason: str = Field(min_length=1, max_length=2000)

    _normalize_marketplace = field_validator("marketplace")(_nonempty_text)
    _normalize_external_id = field_validator("external_id")(_nonempty_text)
    _normalize_reason = field_validator("reason")(_nonempty_text)


class ConfirmCanonicalProductProposalRequest(ApiModel):
    """Input for confirming one current source-backed product proposal."""

    marketplace: str = Field(min_length=1, max_length=64)
    external_id: str = Field(min_length=1, max_length=255)
    reason: str | None = Field(default=None, max_length=2000)

    _normalize_marketplace = field_validator("marketplace")(_nonempty_text)
    _normalize_external_id = field_validator("external_id")(_nonempty_text)
    _normalize_reason = field_validator("reason")(_optional_nonempty_text)


class ResolveCanonicalProductProposalRequest(ApiModel):
    """Input for resolving a proposal to its displayed existing product."""

    marketplace: str = Field(min_length=1, max_length=64)
    external_id: str = Field(min_length=1, max_length=255)
    canonical_product_id: UUID
    reason: str = Field(min_length=1, max_length=2000)

    _normalize_marketplace = field_validator("marketplace")(_nonempty_text)
    _normalize_external_id = field_validator("external_id")(_nonempty_text)
    _normalize_reason = field_validator("reason")(_nonempty_text)


class CanonicalOfferReviewCandidateResponse(ApiModel):
    """Seller-safe representation of one review-confidence candidate."""

    marketplace: str
    external_id: str
    offer_title: str
    offer_url: str | None
    offer_price: Decimal | None
    currency: str | None
    canonical_product_id: UUID
    canonical_product_name: str
    canonical_product_category: str | None
    similarity: float = Field(ge=0.0, le=1.0)
    match_decision: MatchDecision


class CanonicalProductProposalResponse(ApiModel):
    """System-proposed canonical product derived from one unmatched offer."""

    proposal_id: UUID
    marketplace: str
    external_id: str
    offer_title: str
    offer_url: str | None
    offer_price: Decimal | None
    currency: str | None
    proposed_name: str
    proposed_aliases: tuple[str, ...]
    nearest_canonical_product_id: UUID | None
    nearest_canonical_product_name: str | None
    nearest_similarity: float = Field(ge=0.0, le=1.0)
    match_decision: MatchDecision


class CanonicalOfferReviewResponse(ApiModel):
    """Stable response for one persisted canonical offer review decision."""

    decision_id: UUID
    tenant_id: UUID
    marketplace: str
    external_id: str
    canonical_product_id: UUID
    decision: CanonicalOfferDecisionType
    actor_id: str
    actor_type: AdminActorType
    reason: str | None
    request_id: str
    created_at: datetime
    replayed: bool


class CanonicalProductProposalConfirmationResponse(ApiModel):
    """Created canonical product and immutable proposal decision evidence."""

    proposal_id: UUID
    canonical_product_id: UUID
    canonical_product_name: str
    canonical_product_category: str | None
    canonical_product_aliases: tuple[str, ...]
    marketplace: str
    external_id: str
    decision_id: UUID
    decision: CanonicalOfferDecisionType
    created_at: datetime
    replayed: bool


class CanonicalProductProposalResolutionResponse(
    CanonicalProductProposalConfirmationResponse
):
    """Existing canonical product selected through explicit human review."""
