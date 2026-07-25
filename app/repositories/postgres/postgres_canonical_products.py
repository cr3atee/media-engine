from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.canonical_product import CanonicalProduct
from app.models.canonical_product_record import CanonicalProductRecord
from app.repositories.canonical_products import CanonicalProductRepository


class PostgresCanonicalProductRepository(CanonicalProductRepository):
    """PostgreSQL-backed repository for canonical products."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with an existing async database session."""
        self._session = session

    async def save(self, product: CanonicalProduct) -> None:  # type: ignore[override]
        """Persist or update a canonical product."""
        record = await self._session.get(CanonicalProductRecord, product.id)
        if record is None:
            self._session.add(
                CanonicalProductRecord(
                    id=product.id,
                    name=product.name,
                    category=product.category,
                    aliases=list(product.aliases),
                    created_at=datetime.now(UTC),
                )
            )
        else:
            record.name = product.name
            record.category = product.category
            record.aliases = list(product.aliases)

        await self._session.flush()

    async def get_by_id(  # type: ignore[override]
        self,
        id: UUID,
    ) -> CanonicalProduct | None:
        """Return a canonical product by identifier when it exists."""
        record = await self._session.get(CanonicalProductRecord, id)
        if record is None:
            return None
        return self._to_domain(record)

    async def list_all(self) -> Sequence[CanonicalProduct]:  # type: ignore[override]
        """Return all canonical products in insertion order."""
        result = await self._session.execute(
            select(CanonicalProductRecord).order_by(
                CanonicalProductRecord.created_at,
                CanonicalProductRecord.id,
            )
        )
        return tuple(self._to_domain(record) for record in result.scalars())

    @staticmethod
    def _to_domain(record: CanonicalProductRecord) -> CanonicalProduct:
        return CanonicalProduct(
            id=record.id,
            name=record.name,
            category=record.category,
            aliases=tuple(record.aliases),
        )
