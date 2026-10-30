from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID, uuid5

from app.domain.identity import normalize_utc
from app.domain.offer_availability import (
    OfferAvailabilityState,
    OfferAvailabilityStatus,
)
from app.domain.processing import StateTransitionOutcome, StateTransitionResult
from app.parsers.models import ParsedOffer
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.offers import (
    OfferObservationContext,
    OfferRepository,
    resolve_offer_identity_args,
    resolve_offer_marketplace_args,
    resolve_offer_save_args,
)


@dataclass(slots=True, frozen=True)
class _MemoryOfferObservation:
    first_seen_at: datetime
    last_seen_at: datetime
    state_updated_at: datetime
    is_active: bool
    unavailable_since: datetime | None


class MemoryOfferRepository(OfferRepository):
    """In-memory repository for parsed marketplace offers."""

    def __init__(self) -> None:
        """Initialize empty in-memory offer storage."""
        self._offers: list[ParsedOffer] = []
        self._observations: dict[
            tuple[UUID, UUID, str, str],
            _MemoryOfferObservation,
        ] = {}
        self._availability: dict[tuple[UUID, str, str], OfferAvailabilityState] = {}

    async def save(
        self,
        tenant_id: UUID | ParsedOffer,
        offer: ParsedOffer | None = None,
    ) -> None:
        """Store or update a parsed offer in deterministic order."""
        tenant_id, offer = resolve_offer_save_args(tenant_id, offer)
        _validate_tenant(tenant_id, offer.tenant_id)
        if offer.external_id is not None:
            for index, stored_offer in enumerate(self._offers):
                if (
                    stored_offer.tenant_id == tenant_id
                    and stored_offer.marketplace == offer.marketplace
                    and stored_offer.external_id == offer.external_id
                ):
                    self._offers[index] = replace(
                        stored_offer,
                        title=_incoming_or_stored(offer.title, stored_offer.title),
                        url=_incoming_or_stored(offer.url, stored_offer.url),
                        price=_incoming_or_stored(offer.price, stored_offer.price),
                        currency=_incoming_or_stored(
                            offer.currency,
                            stored_offer.currency,
                        ),
                        seller_id=_incoming_or_stored(
                            offer.seller_id,
                            stored_offer.seller_id,
                        ),
                        seller_name=_incoming_or_stored(
                            offer.seller_name,
                            stored_offer.seller_name,
                        ),
                        source_category_id=_incoming_or_stored(
                            offer.source_category_id,
                            stored_offer.source_category_id,
                        ),
                        source_category_name=_incoming_or_stored(
                            offer.source_category_name,
                            stored_offer.source_category_name,
                        ),
                        catalog_hub_code=_incoming_or_stored(
                            offer.catalog_hub_code,
                            stored_offer.catalog_hub_code,
                        ),
                        catalog_section_code=_incoming_or_stored(
                            offer.catalog_section_code,
                            stored_offer.catalog_section_code,
                        ),
                        catalog_source_rule_id=_incoming_or_stored(
                            offer.catalog_source_rule_id,
                            stored_offer.catalog_source_rule_id,
                        ),
                        canonical_product_id=_incoming_or_stored(
                            offer.canonical_product_id,
                            stored_offer.canonical_product_id,
                        ),
                    )
                    self._ensure_availability(offer)
                    return

        self._offers.append(offer)
        self._ensure_availability(offer)

    async def save_observed(
        self,
        context: OfferObservationContext,
        offer: ParsedOffer,
    ) -> None:
        """Store an offer and update its source-scoped availability state."""
        _validate_observation(context, offer)
        await self.save(context.tenant_id, offer)
        if offer.external_id is None:
            return

        key = (
            context.tenant_id,
            context.integration_id,
            context.marketplace,
            offer.external_id,
        )
        stored = self._observations.get(key)
        if stored is None:
            self._observations[key] = _MemoryOfferObservation(
                first_seen_at=context.observed_at,
                last_seen_at=context.observed_at,
                state_updated_at=context.observed_at,
                is_active=True,
                unavailable_since=None,
            )
            return

        is_newest_state = context.observed_at >= stored.state_updated_at
        self._observations[key] = replace(
            stored,
            first_seen_at=min(stored.first_seen_at, context.observed_at),
            last_seen_at=max(stored.last_seen_at, context.observed_at),
            state_updated_at=(
                context.observed_at if is_newest_state else stored.state_updated_at
            ),
            is_active=True if is_newest_state else stored.is_active,
            unavailable_since=None if is_newest_state else stored.unavailable_since,
        )

    async def reconcile_observations(
        self,
        context: OfferObservationContext,
        external_ids: Collection[str],
    ) -> int:
        """Deactivate missing observations without trusting an empty snapshot."""
        observed_ids = frozenset(external_ids)
        if not observed_ids:
            return 0

        deactivated = 0
        for key, observation in tuple(self._observations.items()):
            tenant_id, integration_id, marketplace, external_id = key
            if (
                tenant_id != context.tenant_id
                or integration_id != context.integration_id
                or marketplace != context.marketplace
                or external_id in observed_ids
                or not observation.is_active
                or observation.state_updated_at >= context.observed_at
            ):
                continue
            self._observations[key] = replace(
                observation,
                state_updated_at=context.observed_at,
                is_active=False,
                unavailable_since=context.observed_at,
            )
            deactivated += 1
        return deactivated

    async def get_availability_state(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
    ) -> OfferAvailabilityState | None:
        """Return one manual state without applying active-read filtering."""
        return self._availability.get(
            (tenant_id, marketplace.strip().lower(), external_id.strip())
        )

    async def set_availability_status(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
        status: OfferAvailabilityStatus,
        changed_at: datetime,
        expected_version: int,
    ) -> StateTransitionResult:
        """Apply one optimistic manual availability transition in memory."""
        key = (tenant_id, marketplace.strip().lower(), external_id.strip())
        current = self._availability.get(key)
        if current is None:
            return StateTransitionResult(
                entity_id=UUID(int=0),
                outcome=StateTransitionOutcome.NOT_FOUND,
            )
        if current.version != expected_version:
            return StateTransitionResult(
                entity_id=current.offer_id,
                outcome=StateTransitionOutcome.VERSION_CONFLICT,
                version=current.version,
            )
        target = OfferAvailabilityStatus(status)
        if current.status is target:
            return StateTransitionResult(
                entity_id=current.offer_id,
                outcome=StateTransitionOutcome.INVALID_STATE,
                version=current.version,
            )
        normalized_time = normalize_utc(changed_at, field_name="changed_at")
        updated = replace(
            current,
            status=target,
            version=current.version + 1,
            updated_at=normalized_time,
            retired_at=(
                normalized_time if target is OfferAvailabilityStatus.RETIRED else None
            ),
        )
        self._availability[key] = updated
        return StateTransitionResult(
            entity_id=current.offer_id,
            outcome=StateTransitionOutcome.APPLIED,
            version=updated.version,
        )

    async def get_by_identity(
        self,
        tenant_id: UUID | str,
        marketplace: str,
        external_id: str | None = None,
    ) -> ParsedOffer | None:
        """Return an offer by marketplace and external identifier."""
        tenant_id, marketplace, external_id = resolve_offer_identity_args(
            tenant_id,
            marketplace,
            external_id,
        )
        for offer in self._offers:
            if (
                offer.tenant_id == tenant_id
                and offer.marketplace == marketplace
                and offer.external_id == external_id
                and self._is_active(offer)
            ):
                return offer
        return None

    async def list_by_marketplace(
        self,
        tenant_id: UUID | str,
        marketplace: str | None = None,
    ) -> Sequence[ParsedOffer]:
        """Return parsed offers for one marketplace in insertion order."""
        tenant_id, marketplace = resolve_offer_marketplace_args(
            tenant_id,
            marketplace,
        )
        return tuple(
            offer
            for offer in self._offers
            if (
                offer.tenant_id == tenant_id
                and offer.marketplace == marketplace
                and self._is_active(offer)
            )
        )

    async def list_by_tenant(self, tenant_id: UUID) -> Sequence[ParsedOffer]:
        """Return parsed offers for one tenant in insertion order."""
        return tuple(
            offer
            for offer in self._offers
            if offer.tenant_id == tenant_id and self._is_active(offer)
        )

    async def list_all(self) -> Sequence[ParsedOffer]:
        """Return all parsed offers in insertion order."""
        return tuple(offer for offer in self._offers if self._is_active(offer))

    def _is_active(self, offer: ParsedOffer) -> bool:
        if offer.external_id is None:
            return True
        availability = self._availability.get(
            (offer.tenant_id, offer.marketplace, offer.external_id)
        )
        if (
            availability is not None
            and availability.status is OfferAvailabilityStatus.RETIRED
        ):
            return False
        observations = (
            observation
            for key, observation in self._observations.items()
            if key[0] == offer.tenant_id
            and key[2] == offer.marketplace
            and key[3] == offer.external_id
        )
        states = tuple(observations)
        return not states or any(observation.is_active for observation in states)

    def _ensure_availability(self, offer: ParsedOffer) -> None:
        if offer.external_id is None:
            return
        key = (offer.tenant_id, offer.marketplace, offer.external_id)
        if key in self._availability:
            return
        identity = f"{offer.tenant_id}:{offer.marketplace}:{offer.external_id}"
        self._availability[key] = OfferAvailabilityState(
            offer_id=uuid5(UUID("d60f35ea-a816-41cf-9f68-550b98bcf038"), identity),
            tenant_id=offer.tenant_id,
            marketplace=offer.marketplace,
            external_id=offer.external_id,
            status=OfferAvailabilityStatus.ACTIVE,
            version=1,
            updated_at=datetime.now(UTC),
        )


def _incoming_or_stored[T](incoming: T | None, stored: T | None) -> T | None:
    return stored if incoming is None else incoming


def _validate_tenant(requested: UUID, actual: UUID) -> None:
    if requested != actual:
        msg = f"Offer tenant mismatch: requested {requested}, got {actual}."
        raise RepositoryIdentityConflictError(msg)


def _validate_observation(
    context: OfferObservationContext,
    offer: ParsedOffer,
) -> None:
    _validate_tenant(context.tenant_id, offer.tenant_id)
    if context.marketplace != offer.marketplace:
        msg = (
            "Offer marketplace mismatch: "
            f"observed {context.marketplace}, got {offer.marketplace}."
        )
        raise RepositoryIdentityConflictError(msg)
