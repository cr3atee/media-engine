from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.offer import Offer
from app.parsers.models import ParsedOffer
from app.repositories.offers import OfferRepository


class PostgresOfferRepository(OfferRepository):
    """PostgreSQL-backed repository for parsed marketplace offers."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with an existing async database session."""
        self._session = session

    async def save(self, offer: ParsedOffer) -> None:
        """Persist or update a parsed offer using the active async session."""
        record = None
        if offer.external_id is not None:
            record = await self._get_record_by_identity(
                offer.marketplace,
                offer.external_id,
            )

        if record is None:
            self._session.add(
                Offer(
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
            )
        else:
            record.title = offer.title
            record.url = offer.url
            record.price = offer.price
            record.currency = offer.currency
            record.seller_id = offer.seller_id
            record.seller_name = offer.seller_name
            record.canonical_product_id = offer.canonical_product_id

        await self._session.flush()

    async def get_by_identity(
        self,
        marketplace: str,
        external_id: str,
    ) -> ParsedOffer | None:
        """Return an offer by marketplace and external identifier."""
        record = await self._get_record_by_identity(marketplace, external_id)
        if record is None:
            return None
        return self._to_parsed_offer(record)

    async def list_by_marketplace(self, marketplace: str) -> Sequence[ParsedOffer]:
        """Return parsed offers for one marketplace in insertion order."""
        result = await self._session.execute(
            select(Offer)
            .where(Offer.marketplace == marketplace)
            .order_by(Offer.created_at, Offer.id)
        )
        return tuple(self._to_parsed_offer(offer) for offer in result.scalars())

    async def list_all(self) -> Sequence[ParsedOffer]:
        """Return all parsed offers in insertion order."""
        result = await self._session.execute(
            select(Offer).order_by(Offer.created_at, Offer.id)
        )
        return tuple(self._to_parsed_offer(offer) for offer in result.scalars())

    async def _get_record_by_identity(
        self,
        marketplace: str,
        external_id: str,
    ) -> Offer | None:
        result = await self._session.execute(
            select(Offer)
            .where(
                Offer.marketplace == marketplace,
                Offer.external_id == external_id,
            )
            .order_by(Offer.created_at, Offer.id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _to_parsed_offer(offer: Offer) -> ParsedOffer:
        return ParsedOffer(
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
