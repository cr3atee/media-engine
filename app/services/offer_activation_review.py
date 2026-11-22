"""Human-confirmed activation conditions with atomic updates and immutable audit."""

from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from uuid import UUID, uuid4

from app.domain.activation_conditions import ActivationConditions
from app.domain.admin_actions import (
    AdminAction,
    AdminActionType,
    AdminResourceType,
    build_admin_request_fingerprint,
    normalize_optional_reason,
    utc_now,
)
from app.domain.identity import validate_sha256
from app.parsers.models import ParsedOffer
from app.repositories.provider import RepositoryProvider
from app.services.admin_mutations import AdminCommandContext, AdminMutationResult
from app.services.repository_scope import RepositoryScopeFactory

ACTION = AdminActionType.SET_OFFER_ACTIVATION_CONDITIONS


@dataclass(slots=True, frozen=True, kw_only=True)
class OfferActivationReviewState:
    """Source snapshot and audit revision bound to one form submission."""

    offer_id: UUID
    offer: ParsedOffer
    version: int
    source_fingerprint: str
    reviewed_at: datetime | None


@dataclass(slots=True, frozen=True, kw_only=True)
class ReviewActivationConditionsCommand:
    """An explicit confirmation, or explicit reset to unknown conditions."""

    tenant_id: UUID
    marketplace: str
    external_id: str
    offer_id: UUID
    expected_version: int
    expected_source_fingerprint: str
    conditions: ActivationConditions | None
    reason: str


class ActivationReviewError(ValueError):
    """Stable, sanitized rejection of a review command."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class OfferActivationReviewService:
    """Use existing repository scopes and audit locks; never fetch source pages."""

    def __init__(self, scope: RepositoryScopeFactory) -> None:
        self._scope = scope

    async def get(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
    ) -> OfferActivationReviewState:
        """Return current source facts and explicit conditions, never defaults."""
        marketplace, external_id = _identity(marketplace, external_id)
        async with self._scope() as repos:
            return await _state(repos, tenant_id, marketplace, external_id)

    async def review(
        self,
        command: ReviewActivationConditionsCommand,
        context: AdminCommandContext,
    ) -> AdminMutationResult:
        """Commit a condition-only CAS and full audit in one transaction."""
        if command.tenant_id != context.tenant_id:
            raise ActivationReviewError("permission_denied")
        marketplace, external_id = _identity(command.marketplace, command.external_id)
        if command.expected_version < 1:
            raise ActivationReviewError("activation_version_conflict")
        validate_sha256(
            command.expected_source_fingerprint, field_name="source fingerprint"
        )
        reason = normalize_optional_reason(command.reason)
        if reason is None:
            raise ActivationReviewError("activation_reason_required")
        requested = command.conditions.to_record() if command.conditions else None
        metadata = (
            ("marketplace", marketplace),
            ("external_id", external_id),
            ("source_fingerprint", command.expected_source_fingerprint),
            *_audit_chunks("conditions", _serialize(requested)),
        )
        fingerprint = build_admin_request_fingerprint(
            tenant_id=command.tenant_id,
            actor_id=context.actor_id,
            actor_type=context.actor_type,
            elevated=context.elevated,
            action=ACTION,
            resource_type=AdminResourceType.OFFER,
            resource_id=command.offer_id,
            expected_version=command.expected_version,
            reason=reason,
            metadata=metadata,
        )
        async with self._scope() as repos:
            actions = repos.admin_actions
            await actions.acquire_idempotency_lock(
                f"offer-activation:{command.offer_id}", command.tenant_id
            )
            await actions.acquire_idempotency_lock(
                context.idempotency_key, command.tenant_id
            )
            existing = await actions.get_by_idempotency_key(
                context.idempotency_key, command.tenant_id
            )
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise ActivationReviewError("idempotency_conflict")
                return AdminMutationResult.from_action(existing, replayed=True)
            current = await _state(repos, command.tenant_id, marketplace, external_id)
            if current.offer_id != command.offer_id:
                raise ActivationReviewError("offer_not_found")
            if current.version != command.expected_version:
                raise ActivationReviewError("activation_version_conflict")
            if current.source_fingerprint != command.expected_source_fingerprint:
                raise ActivationReviewError("activation_source_conflict")
            updated = await repos.offers.compare_and_set_activation_conditions(
                command.tenant_id,
                current.offer,
                command.conditions,
            )
            if not updated:
                raise ActivationReviewError("activation_source_conflict")
            action = await actions.append(
                AdminAction(
                    id=uuid4(),
                    tenant_id=command.tenant_id,
                    action=ACTION,
                    resource_type=AdminResourceType.OFFER,
                    resource_id=current.offer_id,
                    previous_state="verified"
                    if current.offer.activation_conditions
                    else "unknown",
                    resulting_state="verified" if command.conditions else "unknown",
                    actor_id=context.actor_id,
                    actor_type=context.actor_type,
                    elevated=context.elevated,
                    request_id=context.request_id,
                    idempotency_key=context.idempotency_key,
                    request_fingerprint=fingerprint,
                    expected_version=current.version,
                    resulting_version=current.version + 1,
                    reason=reason,
                    created_at=utc_now(),
                    metadata=(
                        *metadata,
                        *_audit_chunks("source", _source_snapshot(current.offer)),
                    ),
                )
            )
            return AdminMutationResult.from_action(action, replayed=False)


async def _state(
    repos: RepositoryProvider,
    tenant_id: UUID,
    marketplace: str,
    external_id: str,
) -> OfferActivationReviewState:
    offer = await repos.offers.get_by_identity(tenant_id, marketplace, external_id)
    availability = await repos.offers.get_availability_state(
        tenant_id, marketplace, external_id
    )
    if offer is None or availability is None:
        raise ActivationReviewError("offer_not_found")
    snapshot = replace(offer)
    trail = await repos.admin_actions.list_for_resource(
        AdminResourceType.OFFER, availability.offer_id
    )
    last = max(
        (
            item
            for item in trail
            if item.tenant_id == tenant_id and item.action is ACTION
        ),
        key=lambda item: item.resulting_version,
        default=None,
    )
    return OfferActivationReviewState(
        offer_id=availability.offer_id,
        offer=snapshot,
        version=last.resulting_version if last else 1,
        source_fingerprint=sha256(
            _source_snapshot(snapshot).encode("utf-8")
        ).hexdigest(),
        reviewed_at=last.created_at if last else None,
    )


def _identity(marketplace: str, external_id: str) -> tuple[str, str]:
    marketplace, external_id = marketplace.strip().lower(), external_id.strip()
    if (
        not marketplace
        or len(marketplace) > 64
        or not external_id
        or len(external_id) > 255
    ):
        raise ActivationReviewError("invalid_offer_identity")
    return marketplace, external_id


def _source_snapshot(offer: ParsedOffer) -> str:
    data = asdict(offer)
    data["activation_conditions"] = (
        offer.activation_conditions.to_record() if offer.activation_conditions else None
    )
    return _serialize(data)


def _serialize(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_value,
    )


def _json_value(value: object) -> str:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    raise TypeError("Unsupported source snapshot value.")


def _audit_chunks(prefix: str, text: str) -> tuple[tuple[str, str], ...]:
    # Protect chunk boundaries from the audit contract's whitespace normalization.
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return tuple(
        (f"{prefix}_b64_{i // 240:03d}", encoded[i : i + 240])
        for i in range(0, len(encoded), 240)
    )
