from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, case, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.dialects.postgresql.dml import Insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.domain.offer_availability import (
    OfferAvailabilityState,
    OfferAvailabilityStatus,
)
from app.domain.processing import StateTransitionOutcome, StateTransitionResult
from app.models.offer import Offer
from app.models.offer_source_observation_record import OfferSourceObservationRecord
from app.parsers.models import ParsedOffer
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.offers import (
    OfferObservationContext,
    OfferRepository,
    resolve_offer_identity_args,
    resolve_offer_marketplace_args,
    resolve_offer_save_args,
)


class PostgresOfferRepository(OfferRepository):
    """PostgreSQL-backed repository for parsed marketplace offers."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with an existing async database session."""
        self._session = session

    async def save(
        self,
        tenant_id: UUID | ParsedOffer,
        offer: ParsedOffer | None = None,
    ) -> None:
        """Insert or race-safely update a parsed offer by stable identity."""
        tenant_id, offer = resolve_offer_save_args(tenant_id, offer)
        _validate_tenant(tenant_id, offer.tenant_id)
        await self._session.execute(self._offer_upsert(tenant_id, offer))

    async def save_observed(
        self,
        context: OfferObservationContext,
        offer: ParsedOffer,
    ) -> None:
        """Persist an offer and upsert its source-scoped observation."""
        _validate_observation(context, offer)
        result = await self._session.execute(
            self._offer_upsert(context.tenant_id, offer).returning(Offer.id)
        )
        offer_id = result.scalar_one()
        if offer.external_id is None:
            return

        statement = insert(OfferSourceObservationRecord).values(
            tenant_id=context.tenant_id,
            integration_id=context.integration_id,
            offer_id=offer_id,
            first_seen_at=context.observed_at,
            last_seen_at=context.observed_at,
            state_updated_at=context.observed_at,
            is_active=True,
            unavailable_since=None,
        )
        excluded = statement.excluded
        is_newest_state = (
            excluded.state_updated_at >= OfferSourceObservationRecord.state_updated_at
        )
        statement = statement.on_conflict_do_update(
            index_elements=(
                OfferSourceObservationRecord.tenant_id,
                OfferSourceObservationRecord.integration_id,
                OfferSourceObservationRecord.offer_id,
            ),
            set_={
                "first_seen_at": func.least(
                    OfferSourceObservationRecord.first_seen_at,
                    excluded.first_seen_at,
                ),
                "last_seen_at": func.greatest(
                    OfferSourceObservationRecord.last_seen_at,
                    excluded.last_seen_at,
                ),
                "state_updated_at": func.greatest(
                    OfferSourceObservationRecord.state_updated_at,
                    excluded.state_updated_at,
                ),
                "is_active": case(
                    (is_newest_state, True),
                    else_=OfferSourceObservationRecord.is_active,
                ),
                "unavailable_since": case(
                    (is_newest_state, None),
                    else_=OfferSourceObservationRecord.unavailable_since,
                ),
            },
        )
        await self._session.execute(statement)

    async def reconcile_observations(
        self,
        context: OfferObservationContext,
        external_ids: Collection[str],
    ) -> int:
        """Deactivate missing observations from one safe non-empty source run."""
        observed_ids = tuple(sorted(frozenset(external_ids)))
        if not observed_ids:
            return 0

        missing_offer_ids = select(Offer.id).where(
            Offer.tenant_id == context.tenant_id,
            Offer.marketplace == context.marketplace,
            Offer.external_id.is_not(None),
            Offer.external_id.not_in(observed_ids),
        )
        statement = (
            update(OfferSourceObservationRecord)
            .where(
                OfferSourceObservationRecord.tenant_id == context.tenant_id,
                OfferSourceObservationRecord.integration_id == context.integration_id,
                OfferSourceObservationRecord.offer_id.in_(missing_offer_ids),
                OfferSourceObservationRecord.is_active.is_(True),
                OfferSourceObservationRecord.state_updated_at < context.observed_at,
            )
            .values(
                is_active=False,
                unavailable_since=context.observed_at,
                state_updated_at=context.observed_at,
            )
        )
        result = cast(
            CursorResult[Any],
            await self._session.execute(statement),
        )
        return int(result.rowcount or 0)

    async def get_availability_state(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
    ) -> OfferAvailabilityState | None:
        """Return manual lifecycle state without active-read filtering."""
        result = await self._session.execute(
            select(Offer).where(
                Offer.tenant_id == tenant_id,
                Offer.marketplace == marketplace.strip().lower(),
                Offer.external_id == external_id.strip(),
            )
        )
        record = result.scalar_one_or_none()
        return self._to_availability_state(record) if record is not None else None

    async def set_availability_status(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
        status: OfferAvailabilityStatus,
        changed_at: datetime,
        expected_version: int,
    ) -> StateTransitionResult:
        """Apply one optimistic manual availability transition."""
        target = OfferAvailabilityStatus(status)
        statement = (
            update(Offer)
            .where(
                Offer.tenant_id == tenant_id,
                Offer.marketplace == marketplace.strip().lower(),
                Offer.external_id == external_id.strip(),
                Offer.manual_availability_version == expected_version,
                Offer.manual_availability_status != target.value,
            )
            .values(
                manual_availability_status=target.value,
                manual_availability_version=Offer.manual_availability_version + 1,
                manual_availability_updated_at=changed_at,
                manually_retired_at=(
                    changed_at if target is OfferAvailabilityStatus.RETIRED else None
                ),
            )
            .returning(Offer.id, Offer.manual_availability_version)
        )
        result = await self._session.execute(statement)
        applied = result.one_or_none()
        if applied is not None:
            return StateTransitionResult(
                entity_id=applied.id,
                outcome=StateTransitionOutcome.APPLIED,
                version=applied.manual_availability_version,
            )

        current = await self.get_availability_state(
            tenant_id,
            marketplace,
            external_id,
        )
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
        return StateTransitionResult(
            entity_id=current.offer_id,
            outcome=StateTransitionOutcome.INVALID_STATE,
            version=current.version,
        )

    @staticmethod
    def _offer_upsert(tenant_id: UUID, offer: ParsedOffer) -> Insert:
        statement = insert(Offer).values(
            id=uuid4(),
            tenant_id=tenant_id,
            marketplace=offer.marketplace,
            external_id=offer.external_id,
            title=offer.title,
            url=offer.url,
            price=offer.price,
            currency=offer.currency,
            seller_id=offer.seller_id,
            seller_name=offer.seller_name,
            canonical_product_id=offer.canonical_product_id,
            created_at=datetime.now(UTC),
        )

        if offer.external_id is not None:
            excluded = statement.excluded
            statement = statement.on_conflict_do_update(
                index_elements=(Offer.tenant_id, Offer.marketplace, Offer.external_id),
                index_where=Offer.external_id.is_not(None),
                set_={
                    "title": func.coalesce(excluded.title, Offer.title),
                    "url": func.coalesce(excluded.url, Offer.url),
                    "price": func.coalesce(excluded.price, Offer.price),
                    "currency": func.coalesce(excluded.currency, Offer.currency),
                    "seller_id": func.coalesce(excluded.seller_id, Offer.seller_id),
                    "seller_name": func.coalesce(
                        excluded.seller_name,
                        Offer.seller_name,
                    ),
                    "canonical_product_id": func.coalesce(
                        excluded.canonical_product_id,
                        Offer.canonical_product_id,
                    ),
                },
            )

        return statement

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
        record = await self._get_record_by_identity(tenant_id, marketplace, external_id)
        if record is None:
            return None
        return self._to_parsed_offer(record)

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
        result = await self._session.execute(
            select(Offer)
            .where(
                Offer.tenant_id == tenant_id,
                Offer.marketplace == marketplace,
                self._active_offer_predicate(),
            )
            .order_by(Offer.created_at, Offer.id)
        )
        return tuple(self._to_parsed_offer(offer) for offer in result.scalars())

    async def list_by_tenant(self, tenant_id: UUID) -> Sequence[ParsedOffer]:
        """Return parsed offers for one tenant in insertion order."""
        result = await self._session.execute(
            select(Offer)
            .where(Offer.tenant_id == tenant_id, self._active_offer_predicate())
            .order_by(Offer.created_at, Offer.id)
        )
        return tuple(self._to_parsed_offer(offer) for offer in result.scalars())

    async def list_all(self) -> Sequence[ParsedOffer]:
        """Return all parsed offers in insertion order."""
        result = await self._session.execute(
            select(Offer)
            .where(self._active_offer_predicate())
            .order_by(Offer.created_at, Offer.id)
        )
        return tuple(self._to_parsed_offer(offer) for offer in result.scalars())

    async def _get_record_by_identity(
        self,
        tenant_id: UUID,
        marketplace: str,
        external_id: str,
    ) -> Offer | None:
        result = await self._session.execute(
            select(Offer)
            .where(
                Offer.tenant_id == tenant_id,
                Offer.marketplace == marketplace,
                Offer.external_id == external_id,
                self._active_offer_predicate(),
            )
            .order_by(Offer.created_at, Offer.id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _active_offer_predicate() -> ColumnElement[bool]:
        any_observation = (
            exists()
            .where(
                OfferSourceObservationRecord.tenant_id == Offer.tenant_id,
                OfferSourceObservationRecord.offer_id == Offer.id,
            )
            .correlate(Offer)
        )
        active_observation = (
            exists()
            .where(
                OfferSourceObservationRecord.tenant_id == Offer.tenant_id,
                OfferSourceObservationRecord.offer_id == Offer.id,
                OfferSourceObservationRecord.is_active.is_(True),
            )
            .correlate(Offer)
        )
        return and_(
            Offer.manual_availability_status == OfferAvailabilityStatus.ACTIVE.value,
            or_(~any_observation, active_observation),
        )

    @staticmethod
    def _to_availability_state(offer: Offer) -> OfferAvailabilityState:
        if offer.external_id is None:
            raise RuntimeError("Offer availability identity is incomplete.")
        return OfferAvailabilityState(
            offer_id=offer.id,
            tenant_id=offer.tenant_id,
            marketplace=offer.marketplace,
            external_id=offer.external_id,
            status=OfferAvailabilityStatus(offer.manual_availability_status),
            version=offer.manual_availability_version,
            updated_at=offer.manual_availability_updated_at,
            retired_at=offer.manually_retired_at,
        )

    @staticmethod
    def _to_parsed_offer(offer: Offer) -> ParsedOffer:
        return ParsedOffer(
            tenant_id=offer.tenant_id,
            marketplace=offer.marketplace,
            external_id=offer.external_id,
            title=offer.title,
            url=offer.url,
            price=offer.price,
            currency=offer.currency,
            seller_id=offer.seller_id,
            seller_name=offer.seller_name,
            canonical_product_id=offer.canonical_product_id,
        )


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
