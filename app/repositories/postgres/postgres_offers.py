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

    async def save(self, offer: ParsedOffer) -> None:  # type: ignore[override]
        """Persist a parsed offer using the active async session."""
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
        await self._session.flush()

    async def list_all(self) -> Sequence[ParsedOffer]:  # type: ignore[override]
        """Return all parsed offers in insertion order."""
        result = await self._session.execute(
            select(Offer).order_by(Offer.created_at, Offer.id)
        )
        return tuple(self._to_parsed_offer(offer) for offer in result.scalars())

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
